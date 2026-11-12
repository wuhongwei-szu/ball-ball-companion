# Architecture

## Components

- **cc-connect 1.5.x** — bridges WeChat ilink bots to a local agent. It owns
  sessions, cron jobs, one-shot timers, and platform routing.
- **Codex CLI** — the local agent. It reads `AGENTS.md` / `PERSONA.md` and uses
  the tools in `tools/`.
- **OpenAI API** (model configured in `.codex/config.toml`; example `gpt-6.1-sol`) — the model provider.
- **Python/PowerShell tools** — memory capture, reminders, sending, backups,
  health checks.

## Data flow

1. A user sends a WeChat message.
2. cc-connect maps the user to a channel (`master` or `xi`, internal session
   ids rotate) and runs the agent.
3. The agent replies with `chat_burst.py` (1-3 bubbles + optional sticker) or
   one `send_msg.py` call, then ends with `NO_REPLY`; cc-connect suppresses the
   final marker.
4. `send_msg.py` / `chat_burst.py` write outgoing bubbles to
   `memory/raw/s1|s2/` and `memory/recent_replies.md` (redacted);
   `send_sticker.py` records sticker usage and quotas.
5. Every five minutes `capture_transcripts.py` appends new user/assistant
   messages from the cc-connect session JSON to `memory/raw/`.
6. `capture_review.py` backfills the assistant's own direct replies into raw,
   so consolidation sees both sides. The daily consolidation cron then runs
   `memory_eval.py`, updates `MEMORY.md`, `EVENTS.md`, `STATE.md`, and
   `THREADS.md`, and writes sourced `current_fact` rows with
   `companion_memory.py learn --curator`.
7. At 08:17 `care_scheduler.py` plans 0-2 random care timers for the day.
   Proactive sends use `chat_burst.py --proactive`; each care opportunity
   carries at most one sticker, and proactive messages pause after two
   unanswered attempts.
8. The weekly reflection writes `WEEKLY.md` and `IMPROVEMENTS.md`; a daily
   reminder job marks past reminders expired.

## Configuration

`config/bot.config.json` (gitignored) stores paths, labels, and legacy session
anchors. It never stores tokens or openids. `tools/common.py` derives:

- `MASTER_SESSION` / `XI_SESSION` from `config/shared_memory.json` when its
  subject `session_key` exists in the cc-connect `user_sessions` map; the
  legacy s1/s2 anchors are a fallback.
- `XI_BOT_TOKEN` / `XI_BOT_ACCOUNT` from the second weixin platform block in
  the cc-connect config.
- `XI_CONTEXT_TOKENS` from the account id.

This keeps private values out of the work tree and the public repository.

## Sessions

cc-connect stores its session file under `%USERPROFILE%\.cc-connect\sessions\`.
The filename includes a hash of the agent work directory; set `session_file`
in `bot.config.json` to the actual file. Internal ids such as `s9` / `s10`
rotate; `whoami.py` resolves the current channel and `view_session.py` resolves
the latest active session by openid.

## Timers and cron

- `cron`: recurring jobs (memory consolidation, raw capture, reminder GC,
  weekly reflection, care planning).
- `timer`: one-shot jobs created by `add_reminder.py` and `care_scheduler.py`.
  The timer scheduler fires at the due time, injects a synthetic prompt into
  a fresh side session, and suppresses the start notification
  (`[cron] silent = true`).
