# Architecture

## Components

- **cc-connect 1.5.x** — bridges WeChat ilink bots to a local agent. It owns
  sessions, cron jobs, one-shot timers, and platform routing.
- **Codex CLI** — the local agent. It reads `AGENTS.md` / `PERSONA.md` and uses
  the tools in `tools/`.
- **OpenAI API** (`gpt-6-luna` by default) — the model provider.
- **Python/PowerShell tools** — memory capture, reminders, sending, backups,
  health checks.

## Data flow

1. A user sends a WeChat message.
2. cc-connect maps the user to a session (`s1` or `s2`) and runs the agent.
3. The agent replies with `chat_burst.py` (1-3 bubbles + optional sticker) or
   one `send_msg.py` call, then ends with `NO_REPLY`; cc-connect suppresses the
   final marker.
4. `send_msg.py` / `chat_burst.py` write outgoing bubbles to
   `memory/raw/s1|s2/` and `memory/recent_replies.md` (redacted);
   `send_sticker.py` records sticker usage and quotas.
5. Every five minutes `capture_transcripts.py` appends new user/assistant
   messages from the cc-connect session JSON to `memory/raw/`.
6. At 03:17 the memory consolidation cron reads raw/notes and updates
   `MEMORY.md`, `EVENTS.md`, `STATE.md`, and `THREADS.md`; it can create
   future reminders.
7. At 08:17 `care_scheduler.py` plans 0-3 random care timers for the day.
   Proactive sends use `chat_burst.py --proactive`; stickers are capped at one
   per day and proactive messages pause after two unanswered attempts.

## Configuration

`config/bot.config.json` (gitignored) stores paths, session IDs, and labels.
It never stores tokens or openids. `tools/common.py` derives:

- `MASTER_SESSION` / `XI_SESSION` from `user_sessions` in the cc-connect
  session file (`s1` / `s2`).
- `XI_BOT_TOKEN` / `XI_BOT_ACCOUNT` from the second weixin platform block in
  the cc-connect config.
- `XI_CONTEXT_TOKENS` from the account id.

This keeps private values out of the work tree and the public repository.

## Sessions

cc-connect stores its session file under `%USERPROFILE%\.cc-connect\sessions\`.
The filename includes a hash of the agent work directory; set `session_file`
in `bot.config.json` to the actual file. `s1` is the primary user and `s2` is
the secondary user.

## Timers and cron

- `cron`: recurring jobs (daily news, memory consolidation, raw capture,
  care planning).
- `timer`: one-shot jobs created by `add_reminder.py` and `care_scheduler.py`.
  The timer scheduler fires at the due time, injects a synthetic prompt into
  a fresh side session, and suppresses the start notification
  (`[cron] silent = true`).
