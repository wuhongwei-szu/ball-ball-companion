# Changelog

## v0.1.0 — 2026-11-01

Initial public release, extracted from a private personal deployment.

### Features
- Two WeChat ilink bots bridged by cc-connect 1.5.x to Codex CLI.
- Shared persona and long-term memory for both bots.
- Multi-bubble replies: one short message per bubble, suppressed final reply via `NO_REPLY`.
- One-shot personalized reminders via cc-connect's built-in timer.
- Probabilistic context-driven care: 0-3 opportunities per day, random daytime windows, quiet hours 23:00-07:00.
- Raw conversation capture with secret redaction.
- Nightly memory consolidation, mood/energy state, and cross-session anti-repetition.
- Daily backup, log rotation, watchdog task, and a read-only health check.

### Security
- No tokens, openids, API keys, chats, or personal memory are stored in this repository.
- Private values are read at runtime from cc-connect's config and session files.
- `config/bot.config.json` and runtime data are gitignored.
- Secret scan runs locally and in CI.
