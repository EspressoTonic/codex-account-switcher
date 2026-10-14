"""Run native Codex with an explicit home and bounded, redacted probes."""

import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import time

from .storage import SwitcherError

MINIMUM_VERSION = (0, 144, 6)
PROBE_LIMIT = 16384
# Known native overrides, plus conservative account/provider routing names.
# Unknown provider-specific env_key values cannot be discovered without parsing
# all native config layers; this wrapper does not claim that security boundary.
AUTH_ENV = {
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT_ID", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
    "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CODEX_AUTH_TOKEN",
    "CODEX_REFRESH_TOKEN_URL_OVERRIDE", "CODEX_REVOKE_TOKEN_URL_OVERRIDE",
    "CODEX_APP_SERVER_LOGIN_CLIENT_ID", "CODEX_CHATGPT_BASE_URL",
    "CODEX_SQLITE_HOME", "CODEX_REMOTE", "CODEX_REMOTE_AUTH_TOKEN",
    "CODEX_AUTH_PROVIDER", "CODEX_AUTH_EXTERNAL_TOKEN", "CODEX_WORKLOAD_IDENTITY",
}
PROTECTED_CONFIG = {
    "cli_auth_credentials_store", "forced_login_method", "forced_chatgpt_workspace_id",
    "chatgpt_base_url", "model_provider", "model_providers", "auth", "auth_route",
    "sqlite_home", "log_dir", "codex_home", "secrets", "mcp_servers", "features",
}
BLOCKED_FLAGS = {"--remote", "--remote-auth-token-env", "--profile", "-p",
                 "--oss", "--local-provider", "--enable", "--disable"}
BLOCKED_COMMANDS = {"login", "logout", "app", "app-server", "mcp-server", "mcp",
                    "remote-control", "exec-server", "update", "cloud", "debug", "doctor", "plugin"}


def validate_environment(environment):
    conflicts = sorted(name for name in AUTH_ENV if environment.get(name, "").strip())
    # Reject unrecognized Codex variables as well, so a new native auth route
    # cannot silently take precedence. Keep home, CA and wrapper/runtime labels.
    allowed = {"CODEX_HOME", "CODEX_CA_CERTIFICATE", "CODEX_ACCOUNT_PROFILE", "CODEX_SANDBOX"}
    conflicts += sorted(name for name in environment if name.startswith("CODEX_")
                        and name not in AUTH_ENV and name not in allowed and environment[name].strip())
    if conflicts:
        raise SwitcherError("Account/state overrides are set: " + ", ".join(conflicts)
                            + ". Unset them explicitly before selecting a profile; values were not printed.")


def validate_arguments(arguments):
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            break  # Everything following is native positional data.
        if argument.split("=", 1)[0] in BLOCKED_FLAGS or (argument.startswith("-p") and not argument.startswith("--")):
            raise SwitcherError("Use the named account home directly; remote, config-profile and provider-routing options are not supported.")
        if (argument.startswith("-") and not argument.startswith("--")
                and argument not in ("-h", "-V") and argument[:2] not in ("-c", "-C", "-m", "-s", "-i", "-a", "-o")):
            raise SwitcherError("Use separate native options; combined or unsupported short options are not forwarded.")
        if argument in BLOCKED_COMMANDS:
            raise SwitcherError("This native command is not supported by run. Use the dedicated login/logout/status commands or native Codex directly.")
        value = None
        if argument in ("-c", "--config"):
            index += 1
            if index >= len(arguments):
                raise SwitcherError("A config override is missing its value.")
            value = arguments[index]
        elif argument.startswith("--config="):
            value = argument[len("--config="):]
        elif argument.startswith("-c") and not argument.startswith("--"):
            value = argument[2:].lstrip("=")
        if value is not None:
            key = value.split("=", 1)[0].strip()
            # Restrict key syntax so quoted/dotted TOML keys cannot disguise a
            # protected root. Values are left for native Codex to validate.
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*", key):
                raise SwitcherError("Use simple dotted names for forwarded config overrides.")
            if key.split(".", 1)[0] in PROTECTED_CONFIG:
                raise SwitcherError("That config override could change account, credential or state routing; configure the chosen home explicitly instead.")
        index += 1


def child_environment(profile, environment):
    validate_environment(environment)
    result = environment.copy()
    result["CODEX_HOME"] = profile["home"]
    result["CODEX_ACCOUNT_PROFILE"] = profile["name"]
    return result


def command(binary, profile, arguments):
    overrides = []
    if profile["kind"] == "managed":
        overrides = ["-c", 'cli_auth_credentials_store="' + profile["storage"] + '"',
                     "-c", 'forced_login_method="chatgpt"',
                     "-c", "sqlite_home=" + json.dumps(profile["home"]),
                     "-c", "log_dir=" + json.dumps(str(Path(profile["home"]) / "log"))]
    return [binary, *overrides, *arguments]


def probe(arguments, environment, timeout=10, limit=PROBE_LIMIT):
    """Bound both streams together; no child output is ever logged."""
    child = subprocess.Popen(arguments, env=environment, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (child.stdout, child.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            deadline = time.monotonic() + timeout
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SwitcherError("Native Codex probe timed out; no raw output was printed.")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, min(4096, limit + 1 - len(output)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > limit:
                        raise SwitcherError("Native Codex probe exceeded its output limit; no raw output was printed.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SwitcherError("Native Codex probe timed out; no raw output was printed.")
            try:
                code = child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise SwitcherError("Native Codex probe timed out; no raw output was printed.") from None
            return code, bytes(output)
    finally:
        # Kill the dedicated probe group, including grandchildren holding pipes.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        child.stdout.close()
        child.stderr.close()


def resolve_binary(value):
    selected = shutil.which(value)
    if not selected:
        raise SwitcherError("Codex executable was not found. Install Codex or pass --codex-bin with its absolute path.")
    return str(Path(selected).resolve())


def check_version(binary, environment):
    code, output = probe([binary, "--version"], environment)
    found = re.search(rb"(?m)^codex-cli (\d+)\.(\d+)\.(\d+)\s*$", output)
    if code != 0 or not found:
        raise SwitcherError("Could not verify the native Codex version; no raw output was printed.")
    version = tuple(int(part) for part in found.groups())
    if version < MINIMUM_VERSION:
        raise SwitcherError("Codex 0.144.6 or newer is required by this initial compatibility baseline.")
    return ".".join(str(part) for part in version)


def login_status(binary, profile, environment):
    code, output = probe(command(binary, profile, ["login", "status"]), environment)
    lines = output.splitlines()
    # Native exit 1 also means a storage/config error, so never equate it alone
    # with a signed-out account. Expose known phrases only, not key previews.
    if code == 0:
        methods = {b"Logged in using ChatGPT": "chatgpt",
                   b"Logged in using access token": "access-token",
                   b"Logged in using personal access token": "personal-access-token",
                   b"Logged in using Amazon Bedrock API key": "bedrock-api-key"}
        for line in lines:
            if line in methods:
                return {"state": "authenticated", "method": methods[line]}
            if line.startswith(b"Logged in using an API key - "):
                return {"state": "authenticated", "method": "api-key"}
    if code == 1 and b"Not logged in" in lines:
        return {"state": "signed-out", "method": None}
    return {"state": "check-failed", "method": None}


def interactive(arguments, environment):
    # Keep the parent alive to hold the advisory profile lock. Both processes
    # share the foreground terminal group. Forward signals sent to the wrapper
    # alone; terminal-delivered SIGINT may also reach the native process.
    child = subprocess.Popen(arguments, env=environment)
    previous = {}

    def forward(number, _frame):
        try:
            child.send_signal(number)
        except ProcessLookupError:
            pass

    try:
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[number] = signal.signal(number, forward)
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
