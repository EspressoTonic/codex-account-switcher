import argparse
import json
import os
import sys

from . import __version__
from .launcher import (check_version, child_environment, command, interactive,
                       login_status, resolve_binary, validate_arguments)
from .storage import Registry, SwitcherError, default_state


def parser():
    result = argparse.ArgumentParser(description="Choose a separate Codex account home for each launch.")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--state-dir", help="Private registry directory outside Git (absolute path).")
    result.add_argument("--codex-bin", default="codex", help="Native Codex executable (default: codex on PATH).")
    actions = result.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create", help="Create an isolated ChatGPT account home.")
    create.add_argument("name")
    create.add_argument("--storage", choices=("keyring", "file"), default="keyring")
    create.add_argument("--allow-plaintext", action="store_true", help="Acknowledge plaintext auth.json for file storage.")
    register = actions.add_parser("register", help="Label an existing home without modifying its contents.")
    register.add_argument("name")
    register.add_argument("--home", required=True, help="Existing private Codex home (absolute path).")
    listing = actions.add_parser("list", help="List labels and storage policies; never inspect credentials.")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--paths", action="store_true", help="Include private home paths in output.")
    for action in ("login", "logout", "status", "doctor", "forget", "run"):
        item = actions.add_parser(action, help={
            "login": "Delegate browser or device-code login to native Codex.",
            "logout": "Explicitly log out the chosen native account home.",
            "status": "Check native login status with raw output redacted.",
            "doctor": "Check this profile and native Codex version without reading auth.",
            "forget": "Remove the label; preserve its home and credentials.",
            "run": "Launch native Codex with the chosen account home.",
        }[action])
        item.add_argument("name")
        if action == "login":
            item.add_argument("--device-auth", action="store_true")
        if action in ("logout", "forget"):
            item.add_argument("--confirm", action="store_true")
        if action in ("status", "doctor"):
            item.add_argument("--json", action="store_true")
        if action == "run":
            item.add_argument("arguments", nargs=argparse.REMAINDER, help="Native arguments; optionally start with --.")
    return result


def main(argv=None):
    if sys.platform not in ("linux", "darwin"):
        print("codex-account: Linux and macOS are supported by this initial version.", file=sys.stderr)
        return 2
    options = parser().parse_args(argv)
    # Applies to native children too; no permissive window for new files.
    previous_umask = os.umask(0o077)
    try:
        registry = Registry(options.state_dir or default_state())
        if options.action in ("create", "register"):
            if options.action == "create":
                registry.add(options.name, storage=options.storage, allow_plaintext=options.allow_plaintext)
            else:
                registry.add(options.name, home=options.home)
            print("Registered " + options.name + ". No login was performed.")
            return 0
        if options.action == "list":
            rows = []
            for name, profile in sorted(registry.profiles().items()):
                row = {"name": name, "kind": profile["kind"], "storage": profile["storage"]}
                if options.paths:
                    row["home"] = profile["home"]
                rows.append(row)
            if options.json:
                print(json.dumps({"schema": 1, "profiles": rows}, sort_keys=True))
            elif not rows:
                print("No profiles. Register your existing work home, then create a personal profile.")
            else:
                for row in rows:
                    print("{name}: {kind}, storage={storage}".format(**row)
                          + ("; " + row["home"] if options.paths else ""))
            return 0
        if options.action in ("logout", "forget") and not options.confirm:
            raise SwitcherError("Add --confirm to " + options.action + " this specific profile.")
        if options.action == "forget":
            registry.forget(options.name)
            print("Forgot " + options.name + "; its home and credentials were preserved.")
            return 0
        arguments = []
        if options.action == "run":
            arguments = options.arguments
            if arguments[:1] == ["--"]:
                arguments = arguments[1:]
            validate_arguments(arguments)
        with registry.selected(options.name, exclusive=options.action in ("login", "logout")) as record:
            profile = {**record, "name": options.name}
            environment = child_environment(profile, os.environ)
            binary = resolve_binary(options.codex_bin)
            version = check_version(binary, environment)
            if options.action in ("doctor", "status"):
                result = {"schema": 1, "name": options.name, "storage": profile["storage"],
                          "kind": profile["kind"], "codex_version": version}
                if options.action == "status":
                    result.update(login_status(binary, profile, environment))
                else:
                    result["state"] = "ready"
                if options.json:
                    print(json.dumps(result, sort_keys=True))
                else:
                    print(options.name + ": " + result["state"] + "; storage=" + profile["storage"]
                          + "; Codex " + version + ("; method=" + result["method"] if result.get("method") else ""))
                return 0 if result["state"] in ("ready", "authenticated") else (1 if result["state"] == "signed-out" else 2)
            if options.action == "login":
                arguments = ["login"] + (["--device-auth"] if options.device_auth else [])
            elif options.action == "logout":
                arguments = ["logout"]
            print("codex-account: " + options.name + " (storage=" + profile["storage"] + ")", file=sys.stderr, flush=True)
            return interactive(command(binary, profile, arguments), environment)
    except SwitcherError as error:
        print("codex-account: " + str(error), file=sys.stderr)
        return 2
    except OSError as error:
        # Never include native argv, private paths, or arbitrary exception text.
        print("codex-account: OS operation failed (errno=" + str(error.errno)
              + "). Check profile paths, permissions and the Codex executable; existing data was preserved.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        os.umask(previous_umask)
