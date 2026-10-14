# Codex Account Switcher

A small CLI for choosing work or personal Codex accounts when starting a terminal session. Each profile uses its own `CODEX_HOME`; the switcher never swaps or copies `auth.json`. Work and personal sessions can run at the same time.

Initial version: Linux and macOS, Python 3.9+, native Codex **0.144.6+**. This is the first tested source baseline, not an OpenAI product. There are no third-party runtime dependencies or background processes.

## Install from source

```sh
git clone https://github.com/EspressoTonic/codex-account-switcher.git
cd codex-account-switcher
python3 scripts/check.py
python3 scripts/build.py
mkdir -p "$HOME/.local/bin"
install -m 755 dist/codex-account.pyz "$HOME/.local/bin/codex-account"
```

Add `~/.local/bin` to your shell's PATH if needed. Run `codex-account --help`. You can also run the checkout directly with `python3 -m codex_account_switcher`.

## Work and personal on a Linux server

Use your own Unix login. Confirm that personal-account use is allowed on the company host before logging in.

```sh
# Label the existing work setup, preserving its files and native storage policy.
codex-account register work --home "$HOME/.codex"

# New personal home: keyring credentials, separate config/sessions/logs.
codex-account create personal
codex-account doctor personal
codex-account login personal --device-auth

# Every launch makes the choice explicit.
codex-account run work
codex-account run personal
codex-account run personal -- exec "Explain this repository"
codex-account run work -- resume --last
codex-account status personal
```

Registration requires mode **0700** on the selected home and **0600** on existing `config.toml`/auth files. The wrapper checks metadata and preserves unsafe files. If it reports broad permissions, inspect the named home yourself and explicitly fix those modes; it does not chmod your existing work setup.

Native device-code login needs to be enabled for the account/workspace. Browser login is available by omitting `--device-auth`. The switcher does not implement OAuth or collect tokens. See [official Codex authentication documentation](https://learn.chatgpt.com/docs/auth).

## Headless storage

New profiles require native **keyring** storage. If the Linux keyring/Secret Service is unavailable or locked, native login fails; the switcher does not change to `auto` or silently save plaintext. Configure a supported native keyring first. Availability/encryption/access controls depend on your OS backend; `doctor` does not test keyring access.

For a server where you deliberately accept plaintext native storage:

```sh
codex-account create personal --storage file --allow-plaintext
codex-account login personal --device-auth
```

This leaves native credentials in the personal home's `auth.json`. Modes 0700/0600 restrict other Unix users; they do **not** encrypt the file. Registered homes use their original storage policy, which may already be `file` or `auto`.

## Commands

| Command | Behavior |
| --- | --- |
| `create NAME` | Create a new ChatGPT profile; no login. |
| `register NAME --home PATH` | Label an existing private home; preserve contents. |
| `list [--json] [--paths]` | List metadata; paths require explicit opt-in. |
| `doctor NAME [--json]` | Check home safety, environment and native version; no credential access. |
| `status NAME [--json]` | Native stored-auth check, with bounded/redacted output. |
| `login NAME [--device-auth]` | Native login into that home. |
| `run NAME [-- NATIVE_ARGS...]` | Native session with that selected home. |
| `logout NAME --confirm` | Native logout of that profile. |
| `forget NAME --confirm` | Forget its label; retain all home data and credentials. |

Global options go before the command: `--state-dir ABSOLUTE_PRIVATE_PATH`, `--codex-bin EXECUTABLE`. State defaults to `$XDG_DATA_HOME/codex-account-switcher` or `~/.local/share/codex-account-switcher` on Linux, and `~/Library/Application Support/codex-account-switcher` on macOS. Keep the registry and homes outside Git. Avoid moving homes: native credential namespaces depend on their canonical paths.

`status` reports `authenticated`, `signed-out` or `check-failed` and a method where known. It checks stored authentication, not token freshness, network access, quota or account identity. A profile named `personal` is just a label; complete native login with the intended account and verify the account in Codex. Exit codes: 0 successful check/action; 1 signed out; 2 wrapper/check error; native session exits propagate (128 + signal for signal exits).

## Isolation and compatibility

- No persistent default account. Only the launched child receives the selected home; the current shell and other sessions keep theirs.
- Wrapped runs hold shared profile locks. Login/logout/forget need an exclusive lock. Native clients launched outside this wrapper are not covered.
- Known inherited account/state overrides, such as `CODEX_API_KEY`, `OPENAI_API_KEY`, `CODEX_ACCESS_TOKEN`, auth URL overrides and `CODEX_SQLITE_HOME`, cause an error that names variables without values. Unrecognized nonempty `CODEX_*` variables are also rejected; the selected home, CA setting and wrapper/runtime labels are allowed. Unset conflicts explicitly in the launching shell. Corporate CA/proxy settings remain intact.
- Native remote routing, config-profile layers, provider selection, feature overrides and account/state config overrides are rejected by `run`. Use dedicated wrapper commands for login/logout/status. Normal models, prompts, `exec`, `review` and `resume` can be forwarded. Place literal prompt data following native `--` when it resembles options/commands.
- Registered homes retain their native configuration. Native project/managed config and custom provider variables remain native integration boundaries. Admin restrictions still apply; this tool does not bypass them.
- Separate homes affect CLI sessions only. There is no desktop/IDE account switching, remote app-server integration or AI Usage Bar dependency.

The native [environment contract](https://learn.chatgpt.com/docs/config-file/environment-variables) documents the home and SQLite-home settings. Credential namespacing was inspected in [Codex 0.144.6](https://github.com/openai/codex/blob/rust-v0.144.6/codex-rs/login/src/auth/storage.rs) and its [secrets namespace code](https://github.com/openai/codex/blob/rust-v0.144.6/codex-rs/secrets/src/lib.rs). Newer versions are accepted, but future changes may require compatibility updates.

## Development

```sh
python3 scripts/check.py
```

This runs synthetic security/integration tests, a limited secret guard and zipapp verification without actual account login. CI repeats it on Linux/macOS. [SECURITY.md](SECURITY.md) covers threat boundaries and private data; [ROADMAP.md](ROADMAP.md) records remaining live-validation/release gates. MIT licensed.
