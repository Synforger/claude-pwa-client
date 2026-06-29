# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities via **[GitHub Security Advisories — private vulnerability report](https://github.com/Synforger/claude-pwa-client/security/advisories/new)**. This routes the report privately to the maintainer; do **not** open a public issue for security topics.

There is no public security email. Private vulnerability reporting on this repo is enabled in repo settings → Code security and analysis.

We aim to acknowledge reports within 7 days. Coordinated disclosure timeline is negotiable; default 90 days from acknowledgement.

## Supported versions

Only the `main` branch is supported. There are no tagged releases (= personal project, no release cycle). Always run against the latest `main`.

## Security model (= 前提)

This project is designed for **personal host machines published on a Tailscale tailnet**. The default assumption is:

> Anyone reachable inside the tailnet has the same trust level as someone logged into the host machine.

Within that scope the codebase enforces the following minimum boundaries:

- `/file` (GET / PUT) is restricted to under `$HOME` + a deny-list of secret files (SSH keys, cloud credentials, shell init / history files, `~/.netrc`)
- `/hooks/event` only accepts loopback (= claude CLI hooks are localhost-bound)
- Markdown rendering uses react-markdown's default sanitizer; only the internal `cpc-file://` scheme is allowed alongside http/https
- Web Push VAPID keys + push subscriptions are stored in `backend/secrets/` / `backend/data/` (gitignored)

WebSocket (`/ws/pty/{sid}`, `/views/ws`, `/jsonl/stream/{sid}`) and most `/sessions/*` HTTP endpoints have **no authentication** and rely on the tailnet ACL. Public-internet or multi-tenant deployment requires adding middleware auth — not the supported configuration.

See `README.md § セキュリティモデル` for the same description in Japanese with implementation pointers.

## In scope

- Code injection / RCE in backend (FastAPI, PTY runner, tmux interactions)
- Path traversal / auth bypass / secret leak in HTTP endpoints
- XSS / CSRF / secret leak in the frontend bundle (= shipped via PWA + Service Worker)
- Privilege escalation via the LaunchAgent / install-service flow
- Dependency vulnerabilities that affect runtime (= tracked via `pip-audit` / `npm audit`)
- Accidental commit of secrets to git history

## Out of scope

- Attacks **from inside** the tailnet (= violates the documented threat model; users opting into multi-tenant tailnet must add auth themselves)
- DoS / resource exhaustion (= personal host, capacity is the operator's concern)
- Vulnerabilities in **separate processes** invoked over HTTP/WebRTC: Sunshine, moonlight-web-stream, Tailscale daemon, Claude Code CLI, `claude-agent-sdk`. Please report those upstream:
  - Sunshine → https://github.com/LizardByte/Sunshine/security
  - moonlight-web-stream → https://github.com/MrCreativ3001/moonlight-web-stream
  - Claude Code / claude-agent-sdk → https://docs.claude.com/en/docs/claude-code
  - Tailscale → https://tailscale.com/security/

## Audit log

| Date | Tooling | Result |
|---|---|---|
| 2026-06-29 | `pip-audit` (90+ Python packages incl. transitive) | clean after upgrading aiohttp / starlette / pyjwt / cryptography / python-multipart |
| 2026-06-29 | `npm audit` (122+ npm packages incl. dev) | 0 vulnerabilities |
| 2026-06-29 | `gitleaks detect` (all 678 commits) | 1 RSA private key found in an iOS native pairing artifact (added May 2026, deleted in a later commit). History rewritten via `git filter-repo --invert-paths`, all refs force-pushed; the leaked key has been revoked / unpaired on the corresponding Sunshine host. Post-rewrite gitleaks rescan = clean |

To run the audits locally:
```bash
task lint           # static checks
task test           # backend + frontend tests
pip-audit           # backend transitive dep CVEs
(cd frontend && npm audit)
gitleaks detect     # secret scan over full history
```
