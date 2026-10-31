# Changelog

## v0.1.2 — 2026-11-01

- Document the two different limits: cc-connect's per-session incoming rate
  limit (“消息发送过快，请稍后再试”) and WeChat ilink's proactive send budget.
- Add `[rate_limit]` to the example config with a single-user note.
- Add a README troubleshooting section.

## v0.1.1 — 2026-11-01

- Cap proactive care at 2/day to fit WeChat ilink's ~4-6 proactive sends per
  24 hours; daily news and event reminders share the same budget.
- Handle "send budget exhausted" with a clear local message instead of
  retrying.
- Document the send budget in README and reminder docs.

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
