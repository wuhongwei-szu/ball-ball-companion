# Privacy and security

## What this repository contains

Only generic code, templates, and documentation. It contains **no**:

- WeChat bot tokens or account IDs
- User openids
- OpenAI/GitHub/Slack API keys
- Chat transcripts, memory, notes, or logs
- Sessions, backups, or local configuration

## Where private data lives

| Data | Location | Committed? |
|---|---|---|
| Bot tokens / openids | `%USERPROFILE%\.cc-connect\config.toml` | No |
| Session data | `%USERPROFILE%\.cc-connect\sessions\` | No |
| Bot paths / session IDs | `config/bot.config.json` | No (gitignored) |
| Long-term memory / raw chats | `memory/` | No (gitignored) |
| Local stickers / generated images | `assets/`, `artifacts/` | No (gitignored) |
| Original voice/file attachments | `.cc-connect/attachments/` | No (gitignored and publication scan blocked) |
| Logs / backups | `logs/`, `backups/` | No (gitignored) |
| API key | environment variable / local `.env` | No |

## Runtime derivation

`tools/common.py` reads the cc-connect config and session file at runtime to
derive:

- the full session keys for `s1` / `s2`
- the configured stable bot account bindings inside the selected project,
  with each account's token and context-token path

These values stay in memory and are never written to `bot.config.json` or the
repository.

Original voice analysis uses the audio API chosen for the deployment. It sends
the complete recording, uses the existing regular API key, and does not print
audio payloads or SDK debug bodies. The main chat model and persona remain in use.

## Redaction

`capture_transcripts.py` and `send_msg.py` call `common.redact()` before
writing raw/recent files. It masks common API keys, tokens, passwords, and
private-key blocks. It is a safety net; do not intentionally send secrets to
the bot.

## Repository checks

- `.gitignore` excludes config, memory, logs, sessions, backups, `.codex/`,
  and `.env`.
- `scripts/secret_scan.py` scans for API keys, bot tokens, openids, personal
  Windows paths, and private keys. CI runs it on every push.
- `scripts/sync_to_github.ps1` copies an explicit list of reusable files and
  defaults to preparation only. `-Publish` explicitly enables commit/push;
  it scans the exact staged snapshot and refuses to include unrelated changes.

## Deployment recommendations

- Keep the repository **public** only if you are comfortable with the generic
  code and templates; never commit a filled config or memory.
- Set `allow_from` to the intended users.
- Use an environment variable for `OPENAI_API_KEY`; do not hard-code it.
- `mode = "yolo"` gives the agent full local permissions. Use a sandboxed mode
  or a separate machine if that is not acceptable.
- Treat `memory/` and backups as sensitive personal data: they are as private
  as the conversations they contain.
- Rotate bot tokens if they are ever exposed.

## If you fork this project

Create your own private `config/bot.config.json` and `memory/`; do not open a
pull request that includes them. Run `scripts/secret_scan.py` before every
push.
