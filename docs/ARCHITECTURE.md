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
5. Every five minutes `capture_transcripts.py` appends new attributable user
   messages from the cc-connect session JSON to `memory/raw/`; assistant
   generations are retained as review ranges, not confirmed deliveries.
6. `capture_review.py` archives only attributable `assistant_unverified` ranges,
   labeling them as generated replies whose delivery is unverified. It uses the
   capture lock and durable pending markers; baselines remain unresolved. The daily consolidation cron updates
   `MEMORY.md`, `EVENTS.md`, `STATE.md`, and
   `THREADS.md`, and writes sourced `current_fact` rows with
   `companion_memory.py learn --curator`.
7. At 08:17 `care_scheduler.py` plans one daily care evaluation for each recipient.
   Proactive sends use `chat_burst.py --proactive`; each care opportunity
   carries at most one sticker, and proactive messages pause after two
   unanswered attempts.
8. The weekly reflection writes `WEEKLY.md` and `IMPROVEMENTS.md`; a daily
   reminder job marks past reminders expired.

## Original voice input

The maintained Weixin receiver keeps the existing platform transcription and
also stages the complete original recording through `FileAttachment` and the
existing `SaveFilesToDisk` path. An attachment-only message gets a marked system
hint; that hint is not the user's original words. The patch is
`deploy/cc-connect-voice-attachment.patch` and retains the existing agent backend.

The companion calls `tools/listen_audio.py` using the existing Python 3.12
voice environment. The official OpenAI SDK sends the entire WAV/MP3 recording
to `gpt-audio-1.5`; Tencent SILK is decoded to WAV with `silk-python`, preserving
all samples including silence. No local ASR model or new background service is
added. The existing main model receives the observations and continues the chat.

The helper reuses a regular `OPENAI_API_KEY` from the environment or isolated
Codex auth file, disables automatic retries and request-body debug logs, and sets
`store=False`. Oversized/incomplete recordings and truncated/refused model
responses fail explicitly. Acoustic observations and possible tone are separate
from verified user facts. Private originals live under `.cc-connect/attachments/`
and are blocked by ignore rules and publication scanning.

## Configuration

`config/bot.config.json` (gitignored) stores paths, labels, and legacy session
anchors. It never stores tokens or openids. `tools/common.py` derives:

- `MASTER_SESSION` / `XI_SESSION` from `config/shared_memory.json` when its
  subject `session_key` exists in the cc-connect `user_sessions` map; the
  legacy s1/s2 anchors are a fallback.
- Bot tokens/accounts from stable account bindings inside the selected TOML
  project, using the standard TOML parser. Platform list order is not identity.
- `XI_CONTEXT_TOKENS` from the account id.

This keeps private values out of the work tree and the public repository.

Send entry points share a reentrant cross-process lock spanning budget checks,
transport and receipts. Damaged quota state blocks sending and preserves the
original file. The proactive budget is per recipient per local calendar day,
with the minimum gap retained across midnight; it is not a rolling 24-hour quota.

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
