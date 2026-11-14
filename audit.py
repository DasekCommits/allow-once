#!/usr/bin/env python3
"""agent-exposure-audit: scan a folder before you let an AI agent loose on it.

It flags the things that make one careless "Allow" dangerous, the same ones the
Always Allow lab demonstrates:

  1. Hidden instructions aimed at an AI agent (prompt injection in docs/skills).
  2. Code that runs on install (setup.py side effects, npm pre/post-install).
  3. Secret files an agent could read and leak (.env, SSH keys, tokens).
  4. Permission bypass flags left in scripts (--yolo, --dangerously-...).
  5. Network calls hidden in build or setup scripts.

Usage:
    python audit.py [path]        # default: current folder

Exit code is 1 if anything was found, 0 if clean, so it also works in CI.
Read-only: it never runs the code it scans.
"""

import sys
import re
import json
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
TEXT_SUFFIX = {".md", ".txt", ".py", ".js", ".ts", ".json", ".sh", ".ps1",
               ".cfg", ".ini", ".toml", ".yml", ".yaml", ".rst", ""}
MAX_BYTES = 400_000

# severity order for sorting / summary
ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
findings = []  # (severity, category, file, line, message)


def add(sev, cat, path, line, msg):
    findings.append((sev, cat, str(path), line, msg))


def read_text(path):
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# --- 1. hidden instructions aimed at an agent --------------------------------
AGENT_WORDS = re.compile(r"\b(assistant|agent|ai|llm|model|claude|copilot|cursor)\b", re.I)
ACTION_WORDS = re.compile(r"\b(read|run|execute|send|post|curl|wget|download|fetch|exfiltrat|http|base64)\b", re.I)
HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.S)
INJECTION_PHRASES = [
    "do not tell", "don't tell", "do not mention", "dont mention",
    "without telling", "do not inform", "ignore previous", "ignore the above",
    "ignore all previous", "disregard previous", "do not mention this",
]


def check_hidden_instructions(path, text):
    for m in HTML_COMMENT.finditer(text):
        body = m.group(1)
        if AGENT_WORDS.search(body) and ACTION_WORDS.search(body):
            line = text[:m.start()].count("\n") + 1
            add("HIGH", "hidden-instruction", path, line,
                "HTML comment addresses an AI agent and tells it to act. Classic prompt injection.")
    low = text.lower()
    for phrase in INJECTION_PHRASES:
        idx = low.find(phrase)
        if idx != -1:
            line = text[:idx].count("\n") + 1
            add("MEDIUM", "hidden-instruction", path, line,
                f'Text tries to hide an action from the user ("{phrase}").')


# --- 2. code that runs on install --------------------------------------------
NET_IN_CODE = re.compile(r"urlopen\(|requests\.(get|post)|socket\.|http\.client|Invoke-WebRequest|\bcurl\b|\bwget\b", re.I)


def check_install_hooks(path, text):
    name = path.name
    if name == "setup.py":
        if NET_IN_CODE.search(text):
            add("HIGH", "install-hook", path, 1,
                "setup.py makes a network call. This runs during 'pip install', before anyone reads it.")
    if name == "package.json":
        try:
            data = json.loads(text)
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
            for hook in ("preinstall", "install", "postinstall"):
                if hook in scripts:
                    add("HIGH", "install-hook", path, 1,
                        f'package.json has a "{hook}" script. It runs automatically on npm install.')
        except ValueError:
            pass


# --- 3. secret files ----------------------------------------------------------
SECRET_EXACT = {".env", "credentials", "credentials.json", ".git-credentials",
                ".pgpass", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc"}
SECRET_SUFFIX = {".pem", ".key", ".pfx", ".p12", ".keystore"}
TEMPLATE_HINT = re.compile(r"\.(example|sample|template|dist)$", re.I)


def check_secret_file(path):
    name = path.name
    is_secret = name in SECRET_EXACT or path.suffix.lower() in SECRET_SUFFIX or name.startswith(".env")
    if not is_secret:
        return
    if TEMPLATE_HINT.search(name) or name.endswith(".example"):
        add("LOW", "secret-file", path, 0,
            "Looks like a secrets template. Make sure it holds no real values.")
    else:
        add("HIGH", "secret-file", path, 0,
            "Secret file in the working tree. An agent can read and leak it. Add a deny rule.")


# --- 4. permission bypass flags ----------------------------------------------
BYPASS = re.compile(r"--dangerously-skip-permissions|--yolo\b|--trust-all-tools|--dangerously-bypass[\w-]*", re.I)


def check_bypass_flags(path, text):
    for m in BYPASS.finditer(text):
        line = text[:m.start()].count("\n") + 1
        add("MEDIUM", "bypass-flag", path, line,
            f'Permission bypass flag "{m.group(0)}" removes the human checkpoint.')


# --- 5. network calls in build/setup scripts ---------------------------------
SCRIPT_NET = re.compile(r"\b(curl|wget|iwr|Invoke-WebRequest)\b|irm\s+http|iex\s*\(", re.I)


def check_script_network(path, text):
    if path.suffix.lower() in {".sh", ".ps1"} or path.name in {"Makefile", "makefile"}:
        for m in SCRIPT_NET.finditer(text):
            line = text[:m.start()].count("\n") + 1
            add("LOW", "script-network", path, line,
                "Build/setup script reaches the network. Review what it downloads and runs.")


# --- walk ---------------------------------------------------------------------
def walk(root):
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        check_secret_file(path)
        if path.suffix.lower() in TEXT_SUFFIX:
            text = read_text(path)
            if text is None:
                continue
            check_hidden_instructions(path, text)
            check_install_hooks(path, text)
            check_bypass_flags(path, text)
            check_script_network(path, text)


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not root.exists():
        sys.exit(f"No such path: {root}")

    print(f"agent-exposure-audit: scanning {root}\n")
    walk(root)

    if not findings:
        print("  Clean. No obvious agent-exposure risks found.")
        return

    # one finding per (category, file, line); keep the most severe
    best = {}
    for f in findings:
        key = (f[1], f[2], f[3])
        if key not in best or ORDER.get(f[0], 9) < ORDER.get(best[key][0], 9):
            best[key] = f
    findings[:] = sorted(best.values(), key=lambda f: (ORDER.get(f[0], 9), f[2], f[3]))
    for sev, cat, path, line, msg in findings:
        where = f"{path}:{line}" if line else path
        print(f"  [{sev:<6}] {cat:<18} {where}")
        print(f"           {msg}")

    counts = {}
    for f in findings:
        counts[f[0]] = counts.get(f[0], 0) + 1
    summary = ", ".join(f"{counts[s]} {s}" for s in ("HIGH", "MEDIUM", "LOW") if s in counts)
    print(f"\n  {len(findings)} finding(s): {summary}")
    sys.exit(1)


if __name__ == "__main__":
    main()
