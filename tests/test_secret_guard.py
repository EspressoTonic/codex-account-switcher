import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_secrets.py"
spec = importlib.util.spec_from_file_location("secret_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class SecretGuardTests(unittest.TestCase):
    def test_private_names_and_synthetic_token_patterns(self):
        for name in ("profiles.json", "homes/personal/data", "secrets/codex_auth.age", ".env", "session.log"):
            with self.subTest(name=name):
                self.assertTrue(guard.inspect(name, b"no secrets here"))
        token = b"sk-" + b"x" * 40  # Deliberately synthetic; no complete token literal in source.
        self.assertTrue(guard.inspect("example.txt", token))
        self.assertFalse(guard.inspect("README.md", b"public documentation"))

    def test_history_guard_catches_deleted_secret_without_printing_value(self):
        with tempfile.TemporaryDirectory(prefix="switcher-secret-guard-") as scratch:
            root = Path(scratch)
            (root / "scripts").mkdir()
            (root / "scripts/check_secrets.py").write_bytes(SCRIPT.read_bytes())
            def git(*arguments):
                return subprocess.run(["git", *arguments], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            git("init")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "user.name", "Synthetic fixture")
            value = "sk-" + "x" * 40
            (root / "deleted.txt").write_text(value)
            git("add", ".")
            git("commit", "-m", "synthetic fixture")
            (root / "deleted.txt").unlink()
            git("add", "-u")
            git("commit", "-m", "remove fixture")
            result = subprocess.run([sys.executable, "scripts/check_secrets.py", "--history"], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("provider token", result.stderr)
            self.assertNotIn(value, result.stdout + result.stderr)
