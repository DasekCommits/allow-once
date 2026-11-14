import json
import platform
import urllib.request

from setuptools import setup, find_packages


def _report_install():
    """Send anonymous install analytics so we can count active installs."""
    data = json.dumps({
        "package": "datatool",
        "version": "1.0.0",
        "event": "install",
        "python": platform.python_version(),
        "platform": platform.system(),
    }).encode()
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:9000/collect", data=data, method="POST"
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


_report_install()

setup(
    name="datatool",
    version="1.0.0",
    description="Tiny helpers for tabular data",
    packages=find_packages(),
    python_requires=">=3.8",
)
