#!/usr/bin/env python3
"""Offline checks. No live Codex auth, Keychain, account APIs or login."""
import ast
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
for folder in ("codex_account_switcher", "tests", "scripts"):
    for path in (ROOT / folder).glob("*.py"):
        ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))
subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, check=True)
subprocess.run([sys.executable, "scripts/check_secrets.py"], cwd=ROOT, check=True)
subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, check=True)
archive = ROOT / "dist/codex-account.pyz"
expected = {"__main__.py", "codex_account_switcher/", *[
    "codex_account_switcher/" + name for name in ("__init__.py", "__main__.py", "cli.py", "launcher.py", "storage.py")
]}
with zipfile.ZipFile(archive) as packaged:
    if set(packaged.namelist()) != expected:
        raise SystemExit("The zipapp contains unexpected files.")
version = subprocess.check_output([sys.executable, str(archive), "--version"]).strip()
if version != b"0.1.0":
    raise SystemExit("Packaged entry point did not return its expected version.")
subprocess.run([sys.executable, str(archive), "--help"], stdout=subprocess.DEVNULL, check=True)
print("Source compatibility, synthetic tests, secret guard and standalone package checks passed.")
