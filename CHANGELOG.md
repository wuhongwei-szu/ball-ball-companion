## 2026-11-12 - Memory evolution, comfort stickers and channel identity

- Add viewer-first, relevance-filtered memory retrieval; the current person's
  and shared facts are preferred, and cross-person facts are injected only when
  the message explicitly mentions the other person. `memory_search.py` now
  attributes MEMORY.md sections by person.
- Add `capture_review.py` to backfill the assistant's own direct replies into
  raw transcripts; the daily consolidation now runs it before reading raw.
- Add `companion_memory.py learn --curator` for the silent daily consolidation,
  plus sourced/versioned `current_fact` writes and a small `memory_eval.py`
  regression set (private deployment-specific cases are not published).
- Add a weekly reflection job (`WEEKLY.md`, `CARE_LOG.md`) that reviews
  proactive-care quality and updates open topics/state. It also maintains
  `IMPROVEMENTS.md`: low-risk fixes (facts, tags, notes, reminders) are applied
  directly; changes to persona/rules/send behavior are proposals only.
- Add a `comfort` sticker category with semantic overlay
  `assets/stickers/sticker_tags.json`, `sticker_tag.py` (auto/set/list), and
  comfort-aware selection that does not narrow to one style.
- Add `whoami.py` and `view_session.py` so each bot knows its channel and
  session lookup no longer hard-codes s1/s2; add fast-ack guidance for tasks
  expected to take more than 15 seconds.
- Add a small MemGPT-style core memory: `config/core_memory.json` lists stable
  fact keys that are always injected for the current viewer; the query-matched
  facts and sources remain ranked below the core, and the other person's private
  facts are still excluded unless explicitly mentioned.
- Add fact-level importance, access count, 30-day decay and temporal validity:
  `recall()` records accesses and ranks by relevance/importance/decay/access;
  `learn --valid-until` marks time-bound facts, and the daily `expire` command
  retires them while preserving source history.
- Add `deploy/cc-connect-usage-balance.patch` and
  `docs/CC_CONNECT_USAGE_PATCH.md`: an env-driven cc-connect patch that appends
  the Platform Pro-credit estimate to `/usage` without changing its existing
  output. The cache is written by `usage_report.py`; credentials remain local.
- Add a WeChat plain-text sanitizer in `send_msg.py` / `chat_burst.py` and a
  `reminder_admin.py` lifecycle/GC tool. The sanitizer strips paired `**bold**`
  but keeps math such as `2**3` and Python dunders such as `__name__`.
- Split backups into a light daily archive (memory/tools/config/sessions and
  sticker metadata) and a Sunday full archive (also assets images and the
  cc-connect binary). Retention is 14 daily / 28 full; legacy backups keep the
  newest plus 7 days.
- Add `usage_report.py`: ChatGPT OAuth subscription usage (plan/window/reset)
  plus OpenAI Platform month-to-date cost and an estimated remaining Pro
  API-credit grant when an Admin key with `api.usage.read` is configured.
  Pro credits are monthly grants that expire at the end of the billing cycle
  and do not roll over; the official balance stays on Platform. The normal
  project key cannot read Platform billing; the legacy prepaid-credit endpoint
  needs a browser session key and is optional. Credentials are never printed
  or committed. Amounts should be written as `14.59 美元`/`usd 14.59`, not
  `$14.59`, because PowerShell expands `$14` as a variable.
- Structure pass: trim unrelated global environment sections from the private
  AGENTS prompt, derive send sessions from `shared_memory.json` with the legacy
  s1/s2 anchor as fallback, let `sticker_review.py` auto-select the dedicated
  review venv when present, and move one-off maintenance prompts out of
  `tools/`.
- Prune unused sticker categories from the admin catalog and use `like` as the
  unknown-folder fallback, so the manifest/category list matches AGENTS and
  `CATEGORIES.md` instead of advertising categories with no images. Learned and
  imported stickers also default to `like` instead of the removed `reply`
  category.

## 2026-11-07 - Sync deployed capture and midnight interval repairs

- Recognize generated care/reminder prompts during conservative capture.
- Preserve the proactive minimum interval across midnight.
- Add 15 synthetic checks, with one expected failure for a pre-existing legacy marker false-positive.

## 2026-11-07 - Reconcile deployed application source

- Recover current reusable tools, stable account bindings, conservative capture,
  attributed shared memory, and sticker/voice utilities.
- Add synthetic memory regression tests and private configuration templates.
- See docs/source-reconciliation.md for scope and remaining un-deployed repairs.

# Changelog

## v0.2.6 — 2026-11-01

- Add `--sticker-prefer` keyword filtering and allow comfort stickers when the
  user is down (instead of withholding all stickers).
- Tune Xiaoxiao defaults to `-8% / +5Hz / -5%` and expose rate/pitch/volume
  overrides.
- Add natural-conversation guidance: avoid checklist-style care phrases and
  read-aloud script tone.

## v0.2.5 — 2026-11-01

- Add `send_tts.py`: Edge TTS `zh-CN-XiaoxiaoNeural` voice, delivered as an
  MP3 file because iLink rejects native voice items with `ret=-1`.
- Add direct iLink file sending (`send_xi.py --file`) for the secondary bot.
- Document the optional `.venv-voice` setup and voice safety budget.

## v0.2.4 — 2026-11-01

- Run as close to the iLink limit as is safe: proactive messages share a
  local 4-message/24h budget with a 5-minute gap; chat bursts allow up to 6
  messages; stickers allow 12/day with a 30-second cooldown. All are
  configurable, and `0` disables a local cap.
- Keep the distinction explicit: these local limits protect the account; the
  iLink server's `ret=-2` throttle cannot be removed locally.

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
