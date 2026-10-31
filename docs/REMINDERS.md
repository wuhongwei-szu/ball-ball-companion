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
reads `PERSONA.md` / `MEMORY.md` / `STATE.md`, writes a personalized reminder
via `send_msg.py`, and ends with `NO_REPLY`.

- `--owner master|xi|both`
- Rejects times in 23:00-07:00 unless `--allow-night`
- Deduplicates by owner/date/time/title in `memory/reminders.json`
- Requires cc-connect to be running (it uses the local API socket)

## Random care

`care_scheduler.py` runs from the `careplan01` cron at 08:17:

- Rolls 0/1/2 opportunities with weights 55/32/13.
- A day with 0 opportunities sends nothing.
- Times are random between 08:30 and 21:30, at least 2 hours apart.
- No proactive care at 23:00-07:00.
- Capped at 2/day because WeChat ilink throttles proactive sends to roughly
  4-6 per 24h (daily news and event reminders share the same budget).
- Each opportunity is only a chance: the agent decides from `STATE.md`,
  `MEMORY.md`, `EVENTS.md`, and recent raw context whether there is a real
  reason to message. If not, it replies `NO_REPLY`.

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
