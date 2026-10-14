# Initial CLI scope and release gates

Product: explicit work/personal account choice for a new Codex CLI session on Linux with an individual Unix user, plus macOS. Independent optional companion to AI Usage Bar.

Flow: register existing work home → create personal home → native login → run either profile → check native stored auth → explicit logout/forget when requested. Empty registry and unsafe/busy/unavailable states have terminal guidance.

Data: versioned private metadata registry; separate native homes; no copied credentials or transcript ingestion. One process per invoked CLI, advisory profile/registry locks, no daemon/backend/AI calls. Python 3.9+ standard library, standalone zipapp distribution.

Contracts: native argument arrays, fixed home per child, no automatic account choice; keyring default with explicit plaintext opt-in; preserve registered data; native administrator requirements remain enforced; bounded/redacted probes; explicit destructive native logout, metadata-only forget.

Premortem: misleading labels, auth environment taking precedence, unavailable headless keyring, unsafe paths/permissions, simultaneous auth mutation, native config routing outside the profile, future Codex changes and root access on company hosts. SECURITY.md and tests cover the implemented boundaries; real integration behavior requires separate validation.

## Initial implementation

- [x] Create/register/list/forget with private, atomic metadata.
- [x] Per-launch native Codex routing and argument/env validation.
- [x] Native browser/device-code login, status, explicit logout and doctor (delegation tested with fixtures).
- [x] Concurrent runs and auth mutation locks; terminal signal/exit propagation (synthetic process tests).
- [x] Synthetic boundary/integration tests and Linux/macOS CI configuration.
- [x] Separate dependency-free zipapp with source-only content checks.

## Before a supported public binary release

- [ ] Verify native login, refresh, identity and logout for two real accounts under explicitly authorized testing.
- [ ] Verify Linux keyring available/locked/unavailable behavior with no plaintext fallback, plus macOS Keychain behavior.
- [ ] Verify managed company restrictions and separate config/session routing; do not bypass restrictions.
- [ ] Verify terminal Ctrl-C/resize/job-control in actual shells and native TUI; synthetic signal coverage is limited.
- [ ] Publish private vulnerability contact, supported-version policy and user recovery instructions.
- [ ] Add reviewed release artifacts/checksums and rollback procedure. No automated package publishing in initial CI.

Later: shell convenience commands, optional AI Usage Bar metadata integration, optional account identity display through a safe native interface, and better native capability detection. No automatic rotation or quota-limit evasion.

The canonical owner roadmap is `03 Projects/Personal Projects/Codex Account Switcher.md` in the owner's vault, linked to the Production App Roadmap. This file is the repository implementation/release view.
