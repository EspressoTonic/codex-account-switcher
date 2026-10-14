#!/usr/bin/env python3
"""Build a dependency-free zipapp containing only the CLI source."""
from pathlib import Path
import shutil
import tempfile
import zipapp

ROOT = Path(__file__).resolve().parents[1]
destination = ROOT / "dist/codex-account.pyz"
destination.parent.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="codex-account-build-") as scratch:
    source = Path(scratch)
    shutil.copytree(ROOT / "codex_account_switcher", source / "codex_account_switcher",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (source / "__main__.py").write_text("from codex_account_switcher.cli import main\nraise SystemExit(main())\n")
    zipapp.create_archive(source, destination, interpreter="/usr/bin/env python3", compressed=True)
destination.chmod(0o755)
print(str(destination) + " (" + str(destination.stat().st_size) + " bytes)")
