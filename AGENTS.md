# Codex Account Switcher

Independent Linux/macOS Python 3.9+ standard-library CLI. Read README.md and SECURITY.md before changing authentication behavior.

- Work in verified slices; run `python3 scripts/check.py` before committing.
- Tests use synthetic homes and a fake native executable. Never read live credential contents or perform a real login/logout/status during implementation without explicit owner authorization.
- Select an account home per launch. No global current-account setting, credential copying, token export, automatic account rotation or fallback to another identity.
- New profiles use native keyring storage. Plaintext requires explicit user acknowledgement. Registered homes keep their existing config/storage.
- Native Codex owns authentication, refresh and managed requirements. Do not bypass administrator policy or silently strip corporate auth requirements.
- Never print secrets, raw probe output, provider errors, private paths or arbitrary native command arguments in wrapper diagnostics. Paths are opt-in in list output; native interactive output belongs to the user.
- Preserve native account/config data. Forget removes registry metadata only; logout is explicit and profile-scoped.
- Keep runtime state outside Git and optional integration out of AI Usage Bar's core dependency graph.
- Profile labels are not verified account identities. Do not claim isolation from the same Unix user or root, or encryption of native transcripts/logs.
- No public binary release, package publishing or real-account testing as part of ordinary source verification.
