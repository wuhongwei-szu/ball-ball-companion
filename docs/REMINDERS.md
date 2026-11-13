# Reminders and proactive care

## One-shot reminders

`add_reminder.py` wraps cc-connect 1.5's built-in timer:

```bash
python -X utf8 tools/add_reminder.py \
  --owner master --date 2026-11-10 --time 07:30 \
  --title "体测" --note "带水、运动鞋，别迟到"
```

It creates a `timer add --at ...` job targeting the owner's session. At the
due time cc-connect injects a prompt into a fresh side session; the agent
reads `PERSONA.md` / `MEMORY.md` / `STATE.md` / `THREADS.md`, writes a
personalized reminder via `chat_burst.py --proactive`, and ends with
`NO_REPLY`. A sticker is optional; at most one per proactive burst, and it
still counts toward the global sticker daily cap/cooldown. Omit it for urgent
or serious reminders.

- `--owner master|xi|both`
- Rejects times in 23:00-07:00 unless `--allow-night`
- Deduplicates by owner/date/time/title in `memory/reminders.json`
- Creation is journaled under the same lock used by reminder maintenance.
  `creating` / `uncertain` means reconcile remote timers before retrying;
  `both` retries only a recipient whose creation definitely did not start.
- `reminder_admin.py --list` shows status; `--gc` marks past scheduled entries
  expired, and the daily `b03857e6` cron runs it automatically
- Requires cc-connect to be running (it uses the local API socket)

## Random care

`care_scheduler.py` runs from the `careplan01` cron at 08:17:

- Plans one evaluation opportunity per recipient per day. An evaluation may
  decide to send nothing. Existing same-day legacy plans are preserved.
- Times are random between 08:30 and 21:30, at least 2 hours apart.
- No proactive care at 23:00-07:00.
- Each recipient's proactive tools share a local calendar-day budget of
  4 messages and a 5-minute gap. These are local settings, not official limits. Each care
  opportunity sends at most 2 bubbles.
- Each opportunity is only a chance: the agent decides from `STATE.md`,
  `MEMORY.md`, `EVENTS.md`, `THREADS.md`, and recent raw context whether there
  is a real reason to message. If not, it replies `NO_REPLY`.
- Proactive messages use `chat_burst.py --proactive`; iLink may still throttle
  with `ret=-2`; stop and wait, never retry in a loop.

This follows patterns from SillyTavern Time-Awareness (probabilistic triggers),
dsh-proactive / whalecare (daily limit and quiet hours), and cc-connect timers.

## Tuning

Edit the constants in `care_scheduler.py`:

- `WINDOW_START_MIN` / `WINDOW_END_MIN` — safe active window
- `MIN_GAP_MIN` — spacing between opportunities
- `TARGETS` — the recipients evaluated once each

## Troubleshooting

- `No pending timers.` — no upcoming reminders.
- `cc-connect is not running (socket not found)` — start cc-connect first.
- `context_token` expired — the secondary user must message their bot first.
- Timer fired but no message — the agent may have decided `NO_REPLY`; check
  the logs and `memory/raw/`.
- `消息发送过快，请稍后再试` — cc-connect's incoming per-session rate limit
  (default 20/60s), not the model. Set `[rate_limit] max_messages = 0` for a
  trusted single user, or wait.
- `send budget exhausted` — local cc-connect guard; v1.5.0 counts replies too. Use `burst_limit=20` and `burst_window_secs=60` per Weixin platform. Gateway rejections must be handled separately; do not repeatedly retry.
