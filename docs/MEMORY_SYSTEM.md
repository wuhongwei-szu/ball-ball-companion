# Memory system

## Files

| Path | Purpose |
|---|---|
| `memory/raw/s1|s2/YYYY-MM-DD.md` | Redacted raw transcripts |
| `memory/notes/s1|s2/YYYY-MM-DD.md` | Daily notes written by the agent |
| `memory/MEMORY.md` | Shared long-term memory |
| `memory/STATE.md` | Mood label / energy / relationship temperature / small daily note (≤8 lines) |
| `memory/EVENTS.md` | Important dates and commitments |
| `memory/THREADS.md` | Open topics and commitments worth following up (≤10) |
| `memory/sticker_usage.json` | Sticker send history and daily quotas |
| `memory/recent_replies.md` | Last 20 assistant messages |
| `memory/CONFLICTS.md` | Contradictions waiting for a human decision |
| `memory/reminders.json` | Locally created reminder index |
| `memory/.care_plan.json` | Today's randomized care plan |

## Flow

1. **Capture** — `capture_transcripts.py` runs every 5 minutes and appends new
   messages from the cc-connect session JSON to `memory/raw/`.
2. **Send logging** — `send_msg.py` appends each outgoing bubble to raw and
   recent replies.
3. **Consolidate** — the `memcons01` cron runs at 03:17, reads recent raw and
   notes, updates `MEMORY.md`, `EVENTS.md`, `STATE.md`, `THREADS.md`, and can
   create future reminders.
4. **Recall** — a new agent thread reads `PERSONA.md`, `MEMORY.md`, `STATE.md`,
   `THREADS.md`, and `recent_replies.md` before its first reply. For older
   details, `memory_search.py "关键词"` returns a few short snippets; if nothing
   matches, say so instead of guessing.

## Redaction

`common.py` redacts common secret shapes before writing raw/recent:

- `sk-...`, GitHub/Slack tokens, bearer tokens
- password/密码/口令 fields
- API keys/tokens and private-key blocks

It is a safety net, not a guarantee. Do not send secrets to the bot, and do not
keep secrets in memory files.

## Retention

The backup script rotates launch logs after 14 days. Raw/notes/archive are kept
as memory; prune them manually according to your own privacy policy. Remember
that `memory/` and `backups/` are gitignored and must never be committed.

## Sharing between two bots

Both bots share `MEMORY.md`, `STATE.md`, and `EVENTS.md`. Daily notes are kept
per user (`s1` / `s2`) and merged during consolidation. This gives one persona
and one long-term memory while keeping the two chat channels separate.
