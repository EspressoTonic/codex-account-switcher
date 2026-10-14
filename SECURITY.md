# Security boundaries

This tool is a launcher for native Codex, not a credential manager or a security boundary against company administrators. Profile labels are not verified account identities. On a company-owned host, root and processes running as your Unix user may access personal credentials, memory, sessions and workspace data. Corporate authentication restrictions still apply.

## Private data and Git

Never commit native homes, `auth.json`, `.credentials.json`, secrets/keyring exports, session transcripts, history, logs, databases, private registry paths, diagnostic captures or `.env` values. Encrypted credential files also remain private. `.gitignore` and the redacted secret guard cover common cases; neither is a comprehensive detector. A leaked credential requires revocation/rotation through its owner, not just deleting the file from the latest commit.

The wrapper stores only labels, canonical paths, directory identities and storage choices in an owner-only metadata registry. It never opens native credential contents, decodes tokens, scans keyrings, copies auth files, renews tokens, accepts tokens as arguments or exports credentials. Native Codex owns login, refresh and logout. `register` checks file metadata without changing existing home contents.

## At-rest protection

New profiles request native `cli_auth_credentials_store="keyring"`, not `auto`. Codex fails when the selected credential backend is unavailable. Codex 0.144.6 supports both a direct OS store and native encrypted secrets backed by an OS-store key. The native OS backend determines its protection and access controls; this wrapper does not independently encrypt anything or assert that every Linux keyring is configured safely.

`create --storage file --allow-plaintext` deliberately opts into plaintext native `auth.json`. An existing registered home retains its native policy and can already be plaintext. Registry metadata is protected by filesystem permissions, not encrypted. Native transcripts, SQLite state, configuration and logs may be plaintext even with keyring credentials. No custom encryption scheme or fallback keyfile is introduced.

Homes/state must be owned by the current UID, mode 0700, outside Git, with no final-directory symlink. Parent paths are canonicalized and reject writable-by-other-user ancestors (root-owned sticky temporary directories are permitted). Known auth/config files must be owned regular files, mode 0600, with one hard link. Metadata reads/writes use directory descriptors, no-follow bounded reads, 0600 creation and atomic replacement. Directory identities are checked before launch. These checks do not prevent same-UID/root races or audit native arbitrary paths/ACLs.

## Process and account selection

Every launch supplies `CODEX_HOME`. New managed profiles force ChatGPT authentication, chosen storage, and native SQLite/log locations under that home. Registered homes retain native config. The wrapper rejects known inherited account/state overrides and unrecognized nonempty `CODEX_*` variables without printing values, and blocks account/storage/remote-routing overrides in forwarded arguments. Unknown custom provider env keys and native project/managed configuration require separate native review. The wrapper is not a sandbox; a session can execute tools under its native approval policy.

Interactive native login/session output uses the terminal directly; it can include native login links/device codes or native diagnostics. The wrapper does not capture/log it. Version/status probes capture only bounded output for fixed phrase matching and discard it; errors do not disclose child output or arbitrary exception text. Status is not a network/token validity check. Do not paste native login logs or device codes into public reports.

Shared locks protect wrapped runs; login/logout/forget require an exclusive profile lock. Unwrapped native CLI/IDE/desktop processes do not participate, so close those before changing credentials. Logout needs explicit `--confirm`; forget retains the home and tokens. No global current account, account rotation, token imports or automatic recovery login.

## Reporting and verification

Report vulnerabilities privately to the maintainer through an available private channel; do not open public issues containing credentials, private paths or logs. A contact/repository advisory channel should be established before public releases.

Automated checks use synthetic homes, fake Codex executables, and no account network access. Live two-account testing, Linux keyring failure/lock behavior, corporate policy compatibility and future native releases remain manual release gates. See ROADMAP.md. No live-login claim follows from fixture tests.
