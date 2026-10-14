"""Synthetic Codex executable; never reads actual account state."""
import json
import os
from pathlib import Path
import signal
import sys
import time

arguments = sys.argv[1:]
if arguments == ["--version"]:
    print("codex-cli " + os.environ.get("FIXTURE_VERSION", "0.144.6"))
    raise SystemExit(0)
if arguments[-2:] == ["login", "status"]:
    mode = os.environ.get("FIXTURE_STATUS", "chatgpt")
    if mode == "chatgpt":
        print("Logged in using ChatGPT", file=sys.stderr)
        raise SystemExit(0)
    if mode == "signed-out":
        print("Not logged in", file=sys.stderr)
        raise SystemExit(1)
    if mode == "api":
        print("Logged in using an API key - synthetic-private-preview", file=sys.stderr)
        raise SystemExit(0)
    if mode == "overflow":
        sys.stdout.write("SYNTHETIC-PRIVATE-OUTPUT" * 2000)
        sys.stdout.flush()
        time.sleep(60)
    if mode == "hang":
        time.sleep(60)
    print("Error checking login status: SYNTHETIC-PRIVATE-ERROR", file=sys.stderr)
    raise SystemExit(1)
capture = os.environ.get("FIXTURE_CAPTURE")
if capture:
    Path(capture).write_text(json.dumps({"arguments": arguments,
        "home": os.environ["CODEX_HOME"], "label": os.environ["CODEX_ACCOUNT_PROFILE"],
        "ca": os.environ.get("CODEX_CA_CERTIFICATE"), "umask": os.umask(0o077)}))
if os.environ.get("FIXTURE_WAIT"):
    def stop(number, _frame):
        raise SystemExit(128 + number)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        time.sleep(0.1)
raise SystemExit(int(os.environ.get("FIXTURE_EXIT", "0")))
