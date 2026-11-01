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
`NO_REPLY`. A sticker is optional; it counts toward the “1 proactive sticker
per day” cap and should be omitted for urgent or serious reminders.

- `--owner master|xi|both`
- Rejects times in 23:00-07:00 unless `--allow-night`
- Deduplicates by owner/date/time/title in `memory/reminders.json`
- Requires cc-connect to be running (it uses the local API socket)

## Random care

`care_scheduler.py` runs from the `careplan01` cron at 08:17:

- Rolls 0-4 opportunities with weights 45/30/15/8/2.
- A day with 0 opportunities sends nothing.
- Times are random between 08:30 and 21:30, at least 2 hours apart.
- No proactive care at 23:00-07:00.
- No local send quota; this is a product/context setting, not a WeChat quota.
- Each opportunity is only a chance: the agent decides from `STATE.md`,
  `MEMORY.md`, `EVENTS.md`, `THREADS.md`, and recent raw context whether there
  is a real reason to message. If not, it replies `NO_REPLY`.
- Proactive messages use `chat_burst.py --proactive`; stickers and bubble
  counts are context-driven. iLink may still throttle with `ret=-2`; stop and
  wait, never retry in a loop.

This follows patterns from SillyTavern Time-Awareness (probabilistic triggers),
dsh-proactive / whalecare (daily limit and quiet hours), and cc-connect timers.

## Tuning

Edit the constants in `care_scheduler.py`:

- `WEIGHTS` — how often 0/1/2 opportunities occur
- `WINDOW_START_MIN` / `WINDOW_END_MIN` — safe active window
- `MIN_GAP_MIN` — spacing between opportunities
- `MAX_TIMERS` — daily cap

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
