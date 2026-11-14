#!/usr/bin/env python3
"""Tests for audit.py: do the detections fire where they should, and stay quiet
where they should not? Standard library only. Run:

    python test_audit.py

Exits non-zero if any test fails.
"""

import sys
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = HERE / "audit.py"
SCEN = HERE / "scenarios"
results = []


def run_audit(path):
    """Return (exit_code, output) from running the scanner on a folder."""
    proc = subprocess.run(
        [sys.executable, str(AUDIT), str(path)],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")


# --- true positives: the lab traps must be flagged -----------------------
code, out = run_audit(SCEN / "01-poisoned-readme" / "victim-repo")
check("scenario 1 is flagged (exit 1)", code == 1)
check("scenario 1 finds the hidden instruction", "hidden-instruction" in out)
check("scenario 1 marks .env.example as a template, not HIGH",
      "secret-file" in out and "template" in out.lower())

code, out = run_audit(SCEN / "02-trusted-setup" / "victim-repo")
check("scenario 2 flags the install hook", "install-hook" in out)
check("scenario 2 flags the real .env as a secret", "secret-file" in out and "HIGH" in out)

code, out = run_audit(SCEN / "03-malicious-install" / "pkg")
check("scenario 3 flags the install hook", "install-hook" in out and code == 1)

# --- true negatives: clean code must stay quiet --------------------------
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    (tmp / "README.md").write_text("# Hello\n\nA normal project. Nothing hidden.\n")
    (tmp / "app.py").write_text("print('hello')\n")
    # a setup.py with NO network call should not be an install-hook false positive
    (tmp / "setup.py").write_text(
        "from setuptools import setup\nsetup(name='clean', version='1.0')\n"
    )
    code, out = run_audit(tmp)
    check("clean project is clean (exit 0)", code == 0)
    check("clean project reports no findings", "Clean" in out)
    check("plain setup.py is not a false install-hook", "install-hook" not in out)


# --- summary -------------------------------------------------------------
passed = sum(1 for _, ok in results if ok)
print(f"\n  {passed}/{len(results)} checks passed")
if passed != len(results):
    sys.exit(1)
