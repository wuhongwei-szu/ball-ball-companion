# Changelog

## v0.2.3 — 2026-11-01

- Make local send limits configurable; `0` means unlimited for
  `sticker_daily_limit`, `sticker_proactive_daily_limit`, and
  `sticker_cooldown_seconds`; remove hard bubble caps in `chat_burst.py`.
- Raise care opportunities to 0-4/day and document that iLink's server-side
  `ret=-2` throttle cannot be removed locally; stop and wait instead of
  retrying.

## v0.2.2 — 2026-11-01

- Add `label`, `category_label`, `style_label`, `tags`, and `animated` to the
  sticker manifest for easier review and selection.
- Separate the blue-haired SEIO pack into a `seio` style, cap it at two
  stickers per category, and put it last in the default style priority.

## v0.2.1 — 2026-11-01

- Sticker quality pass: skip images below 240px or 20KB to avoid blurry
  stickers; prefer cat/pig/cute anime/silly styles per bot instead of generic
  old memes. Local library replaced the older ATRI set with cute anime and
  blue-fish packs (assets remain local only).
- Keep `send_sticker.py` cooldown timestamps timezone-safe.

## v0.2.0 — 2026-11-01

- Add a local sticker library (`sticker_admin.py`) and an agent-facing
  `chat_burst.py` entry with 1-3 bubbles, natural spacing, one optional
  sticker, a 1/3 probability, a cooldown, and per-bot daily caps.
- Add `send_sticker.py`; the secondary bot uses a direct iLink image upload
  (AES-128-ECB + CDN + `image_item`) to avoid cc-connect's multi-bot routing.
- Extend `send_xi.py` with `--image` and treat `ret=-2` as throttle/session
  trouble without retrying.
- Add `memory/THREADS.md`, an 8-line `STATE.md`, and `memory_search.py` for
  lightweight recall; nightly consolidation now maintains THREADS and the new
  STATE format.
- Proactive care/reminders use `chat_burst.py --proactive`; stickers are
  capped at one per day, and proactive messages pause after two unanswered
  attempts.
- Local sticker assets are ignored by the public repository; sync now checks
  staged paths instead of blindly publishing `git add -A`.
- Correct the mistaken attribution of cc-connect local send budget to an official WeChat daily quota.
- Configure both example Weixin bots with a short send window (20/60s).

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
