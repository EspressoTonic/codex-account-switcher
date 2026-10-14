import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from codex_account_switcher.cli import main
from codex_account_switcher.launcher import (AUTH_ENV, check_version, child_environment,
                                           login_status, probe, validate_arguments)
from codex_account_switcher.storage import Registry, SwitcherError, atomic_write, directory

ROOT = Path(__file__).resolve().parents[1]


class SwitcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-account-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.state = self.base / "state"
        self.registry = Registry(self.state)
        self.fake = self.base / "codex"
        source = (ROOT / "tests/fake_codex.py").read_text()
        self.fake.write_text("#!" + sys.executable + "\n" + source)
        self.fake.chmod(0o700)
        self.environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.base)}

    def profile(self, name="personal"):
        self.registry.add(name)
        return {**self.registry.profiles()[name], "name": name}

    def invoke(self, *arguments, environment=None):
        output, error = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, environment or self.environment, clear=True):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                code = main(["--state-dir", str(self.state), "--codex-bin", str(self.fake), *arguments])
        return code, output.getvalue(), error.getvalue()

    def child(self, *arguments, environment=None):
        return subprocess.Popen([sys.executable, "-m", "codex_account_switcher",
            "--state-dir", str(self.state), "--codex-bin", str(self.fake), *arguments],
            cwd=ROOT, env=environment or self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def wait_capture(self, path, child):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if path.exists():
                return json.loads(path.read_text())
            if child.poll() is not None:
                self.fail("Fixture exited before capture: " + repr(child.communicate()))
            time.sleep(0.02)
        self.fail("Fixture did not start within its deadline.")

    def test_create_defaults_and_permissions(self):
        profile = self.profile()
        home = Path(profile["home"])
        self.assertEqual(profile["storage"], "keyring")
        self.assertEqual(profile["kind"], "managed")
        self.assertEqual(home.stat().st_mode & 0o777, 0o700)
        for path in (self.state / "profiles.json", home / "config.toml"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertIn('forced_login_method = "chatgpt"', (home / "config.toml").read_text())
        self.assertFalse((home / "auth.json").exists())

    def test_plaintext_requires_acknowledgement(self):
        with self.assertRaises(SwitcherError):
            self.registry.add("personal", storage="file")
        self.registry.add("personal", storage="file", allow_plaintext=True)
        self.assertEqual(self.registry.profiles()["personal"]["storage"], "file")

    def test_register_preserves_existing_contents(self):
        work = self.base / "work"
        work.mkdir(mode=0o700)
        contents = {"config.toml": b"# synthetic existing config\n", "auth.json": b"synthetic fixture only\n"}
        for name, value in contents.items():
            path = work / name
            path.write_bytes(value)
            path.chmod(0o600)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in work.iterdir()}
        self.registry.add("work", home=work)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in work.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(self.registry.profiles()["work"]["storage"], "inherit")
        with self.registry.selected("work"):
            pass
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in work.iterdir()})

    def test_names_duplicates_and_nested_homes_rejected(self):
        for name in ("../escape", "", "UPPER", "a/b", "a\n", "x" * 33):
            with self.subTest(name=name), self.assertRaises(SwitcherError):
                self.registry.add(name)
        profile = self.profile()
        with self.assertRaises(SwitcherError):
            self.registry.add("personal")
        with self.assertRaises(SwitcherError):
            self.registry.add("alias", home=profile["home"])
        nested = Path(profile["home"]) / "nested"
        nested.mkdir(mode=0o700)
        with self.assertRaises(SwitcherError):
            self.registry.add("nested", home=nested)

    def test_symlink_and_broad_permissions_rejected_without_repair(self):
        target = self.base / "target"
        target.mkdir(mode=0o700)
        link = self.base / "link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(SwitcherError):
            self.registry.add("linked", home=link)
        target.chmod(0o755)
        with self.assertRaises(SwitcherError):
            self.registry.add("public", home=target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)

    def test_auth_metadata_rejects_unsafe_files_without_reading(self):
        profile = self.profile()
        home = Path(profile["home"])
        path = home / "auth.json"
        path.write_text("SYNTHETIC-PRIVATE-NOT-VALID-JSON")
        path.chmod(0o600)
        with mock.patch("builtins.open", side_effect=AssertionError("Must not read auth contents")):
            with self.registry.selected("personal"):
                pass
        for kind in ("permission", "symlink", "fifo", "hardlink"):
            with self.subTest(kind=kind):
                path.unlink()
                if kind == "permission":
                    path.write_text("synthetic")
                    path.chmod(0o644)
                elif kind == "symlink":
                    path.symlink_to(home / "config.toml")
                elif kind == "fifo":
                    os.mkfifo(path, 0o600)
                else:
                    os.link(home / "config.toml", path)
                with self.assertRaises(SwitcherError):
                    with self.registry.selected("personal"):
                        pass
                self.assertTrue(os.path.lexists(path))

    def test_home_replacement_is_detected(self):
        profile = self.profile()
        home = Path(profile["home"])
        home.rename(home.with_name("saved"))
        home.mkdir(mode=0o700)
        with self.assertRaises(SwitcherError):
            with self.registry.selected("personal"):
                pass

    def test_private_state_outside_git_and_unwritable_ancestors(self):
        repo = self.base / "repo"
        repo.mkdir(mode=0o700)
        (repo / ".git").mkdir()
        with self.assertRaises(SwitcherError):
            Registry(repo / "state").add("personal")
        public = self.base / "public"
        public.mkdir(mode=0o777)
        public.chmod(0o777)
        with self.assertRaises(SwitcherError):
            Registry(public / "state").add("personal")

    def test_native_encrypted_secrets_metadata_is_checked(self):
        profile = self.profile()
        secrets = Path(profile["home"]) / "secrets"
        secrets.mkdir(mode=0o700)
        data = secrets / "codex_auth.age"
        data.write_text("synthetic ciphertext")
        data.chmod(0o600)
        with self.registry.selected("personal"):
            pass
        data.chmod(0o644)
        with self.assertRaises(SwitcherError):
            with self.registry.selected("personal"):
                pass

    def test_corrupt_oversized_and_symlink_registry_preserved(self):
        self.profile()
        path = self.state / "profiles.json"
        for content in (b"not JSON", b"x" * 65537, b'{"schema":2,"profiles":{}}', b'{"schema":true,"profiles":{}}'):
            path.write_bytes(content)
            with self.assertRaises(SwitcherError):
                self.registry.profiles()
            self.assertEqual(path.read_bytes(), content)
        target = self.base / "target.json"
        target.write_text("synthetic preserved")
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(OSError):
            self.registry.profiles()
        self.assertEqual(target.read_text(), "synthetic preserved")

    def test_atomic_write_replaces_destination_link_not_target(self):
        self.state.mkdir(mode=0o700)
        target = self.base / "target"
        target.write_text("preserve")
        (self.state / "data").symlink_to(target)
        with directory(self.state) as fd:
            atomic_write(fd, "data", b"new metadata")
        self.assertEqual(target.read_text(), "preserve")
        self.assertEqual((self.state / "data").read_bytes(), b"new metadata")

    def test_environment_auth_rejection_and_home_selection(self):
        profile = self.profile()
        for name in (*AUTH_ENV, "CODEX_WI_TEST", "CODEX_FUTURE_AUTH_INPUT"):
            with self.subTest(name=name), self.assertRaises(SwitcherError) as caught:
                child_environment(profile, {name: "SYNTHETIC-PRIVATE-VALUE"})
            self.assertNotIn("SYNTHETIC-PRIVATE-VALUE", str(caught.exception))
        original = {"CODEX_HOME": "/old", "CODEX_CA_CERTIFICATE": "/corporate-ca", "HTTPS_PROXY": "https://proxy"}
        actual = child_environment(profile, original)
        self.assertEqual(actual["CODEX_HOME"], profile["home"])
        self.assertEqual(actual["CODEX_CA_CERTIFICATE"], original["CODEX_CA_CERTIFICATE"])
        self.assertEqual(actual["HTTPS_PROXY"], original["HTTPS_PROXY"])
        self.assertEqual(original["CODEX_HOME"], "/old")

    def test_protected_native_arguments(self):
        cases = [["--remote=ws://example"], ["-pwork"], ["--profile", "work"], ["logout"],
                 ["--config", 'cli_auth_credentials_store="auto"'], ["-cforced_login_method=api"],
                 ["--config=\"cli_auth_credentials_store\"=\"file\""], ["-c", "model_providers.custom.env_key=OTHER_KEY"],
                 ["--enable", "some_feature"], ["--oss"], ["--config"], ["-c", "sqlite_home=/shared"], ["-hccli_auth_credentials_store=file"]]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(SwitcherError):
                validate_arguments(arguments)
        validate_arguments(["exec", "-c", 'model_reasoning_effort="high"', "--", "logout"])
        validate_arguments(["resume", "--last"])

    def test_version_baseline(self):
        environment = self.environment.copy()
        self.assertEqual(check_version(str(self.fake), environment), "0.144.6")
        environment["FIXTURE_VERSION"] = "0.100.0"
        with self.assertRaises(SwitcherError):
            check_version(str(self.fake), environment)

    def test_status_redaction_and_config_error_not_signed_out(self):
        profile = self.profile()
        environment = child_environment(profile, self.environment)
        for mode, expected in (("chatgpt", "authenticated"), ("api", "authenticated"),
                               ("signed-out", "signed-out"), ("error", "check-failed")):
            environment["FIXTURE_STATUS"] = mode
            result = login_status(str(self.fake), profile, environment)
            self.assertEqual(result["state"], expected)
            self.assertNotIn("SYNTHETIC", json.dumps(result))
        code, output, error = self.invoke("status", "personal", "--json",
            environment={**self.environment, "FIXTURE_STATUS": "api"})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["method"], "api-key")
        self.assertNotIn("synthetic-private-preview", output + error)

    def test_probe_bounds_and_timeouts(self):
        for mode in ("hang", "overflow"):
            with self.subTest(mode=mode), self.assertRaises(SwitcherError) as caught:
                probe([str(self.fake), "login", "status"],
                    {**self.environment, "FIXTURE_STATUS": mode}, timeout=0.3, limit=1024)
            self.assertNotIn("SYNTHETIC", str(caught.exception))

    def test_login_logout_and_forget_confirmation(self):
        profile = self.profile()
        capture = self.base / "capture"
        environment = {**self.environment, "FIXTURE_CAPTURE": str(capture)}
        code, _, _ = self.invoke("login", "personal", "--device-auth", environment=environment)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(capture.read_text())["arguments"][-2:], ["login", "--device-auth"])
        for action in ("logout", "forget"):
            self.assertEqual(self.invoke(action, "personal")[0], 2)
        self.assertEqual(self.invoke("logout", "personal", "--confirm", environment=environment)[0], 0)
        self.assertEqual(json.loads(capture.read_text())["arguments"][-1], "logout")
        self.assertEqual(self.invoke("forget", "personal", "--confirm")[0], 0)
        self.assertTrue(Path(profile["home"]).is_dir())
        self.assertEqual(self.registry.profiles(), {})

    def test_list_paths_opt_in_and_native_exit_passthrough(self):
        self.profile()
        code, output, _ = self.invoke("list", "--json")
        self.assertEqual(code, 0)
        self.assertNotIn(str(self.base), output)
        self.assertNotIn("home", json.loads(output)["profiles"][0])
        code, _, _ = self.invoke("run", "personal", "--", "exec", "--", "synthetic prompt",
            environment={**self.environment, "FIXTURE_EXIT": "7"})
        self.assertEqual(code, 7)

    def test_invalid_cli_arguments_do_not_echo_supplied_values(self):
        for arguments in (["--unexpected=SYNTHETIC-PRIVATE-VALUE", "list"],
                          ["SYNTHETIC-PRIVATE-VALUE"],
                          ["create", "personal", "--storage", "SYNTHETIC-PRIVATE-VALUE"]):
            with self.subTest(arguments=arguments):
                output, error = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    with self.assertRaises(SystemExit) as caught:
                        main(arguments)
                self.assertEqual(caught.exception.code, 2)
                self.assertNotIn("SYNTHETIC-PRIVATE-VALUE", output.getvalue() + error.getvalue())

    def test_unknown_environment_variable_names_are_sanitized(self):
        profile = self.profile()
        with self.assertRaises(SwitcherError) as caught:
            child_environment(profile, {"CODEX_\nSYNTHETIC-PRIVATE-NAME": "synthetic"})
        self.assertNotIn("SYNTHETIC-PRIVATE-NAME", str(caught.exception))

    def test_two_profiles_run_concurrently_and_login_cannot_replace_active_auth(self):
        profiles = [self.profile("work"), self.profile("personal")]
        children = []
        try:
            for profile in profiles:
                capture = self.base / (profile["name"] + "-capture")
                child = self.child("run", profile["name"], environment={**self.environment,
                    "FIXTURE_CAPTURE": str(capture), "FIXTURE_WAIT": "1", "CODEX_CA_CERTIFICATE": "/ca"})
                children.append(child)
                result = self.wait_capture(capture, child)
                self.assertEqual(result["home"], profile["home"])
                self.assertEqual(result["label"], profile["name"])
                self.assertEqual(result["umask"], 0o077)
                self.assertEqual(result["ca"], "/ca")
            for action in ("login", "logout", "forget"):
                args = [action, "work"] + (["--confirm"] if action != "login" else [])
                code, _, error = self.invoke(*args)
                self.assertEqual(code, 2)
                self.assertIn("busy", error)
            # Another run on the same home may share the lock.
            self.assertEqual(self.invoke("run", "work")[0], 0)
        finally:
            for child in children:
                child.terminate()
                output, error = child.communicate(timeout=8)
                self.assertEqual(child.returncode, 143, (output, error))
        self.assertEqual(self.invoke("login", "work")[0], 0)

    def test_concurrent_registry_updates_keep_all_profiles(self):
        children = [self.child("create", "profile" + str(index)) for index in range(6)]
        for child in children:
            output, error = child.communicate(timeout=8)
            self.assertEqual(child.returncode, 0, (output, error))
        self.assertEqual(len(self.registry.profiles()), 6)


if __name__ == "__main__":
    unittest.main()
