# Reminders and proactive care

## One-shot reminders

`add_reminder.py` wraps cc-connect 1.5's built-in timer:

```bash
python -X utf8 tools/add_reminder.py \
  --owner master --date 2026-11-10 --time 07:30 \
  --title "体测" --note "带水、运动鞋，别迟到"
```

It creates a muted native `timer add --exec ...` job targeting the owner's
stable account. `reminder_send.py` combines every active item for that owner
and minute into one complete text message. Additional same-time items reuse
the timer. Reminder text contains every title and note; it is not truncated
to a bubble limit and does not depend on a model deciding to send.

Ordinary reminders then attempt one optional local `work` sticker, using the
same selected-sticker probability (1.0), image cooldown, daily image cap, and
proactive image cap as `chat_burst.py`. Text acceptance, index status, and
its receipt accounting are durably completed first. The image has its own
durable one-attempt marker; image failure or interrupted bookkeeping never
resends the text or retries the image. Known remaining reminder groups for
the same recipient/day reserve one text budget slot each before an image
can use an extra slot. Normal chat and proactive-care sticker rules are unchanged.

Use `--sticker <category>` to select another local category. Use `--urgent`
for serious/urgent events or `--text-only` for an explicit text-only request;
any such item makes its whole same-time batch text-only. During migration,
classify serious legacy entries with `urgent: true` or `text_only: true`.
Late receipt recovery finishes accounting only and never introduces a new image.

The sender holds the ordinary outbound lock while checking the proactive
budget, sending, and recording the result. Only the maintained cc-connect
CLI's successful exit plus its exact success acknowledgment is accepted.
This is platform acceptance, not proof that the recipient read the message.
The delivery journal is `memory/reminders.json.delivery.json`:

- `blocked`: no send began (budget/gap, quiet hours, or a local precondition).
  The maintenance dispatcher can try again within 60 minutes of the due time.
- `sending` after an interrupted process, or `uncertain`: a send might have
  happened. Never automatically resend; reconcile the receipt first.
- `accepted`: count one proactive message for the complete batch. Its receipt
  ID is stored atomically with the counter, so recovery does not double-count
  or resend. Index/log failures do not turn acceptance into permission to retry.
- `missed`: the 60-minute window ended without a send. Keep the item for review.

Actual dispatch still respects 23:00–07:00 unless all items in the batch were
explicitly created with `--allow-night`. Expired, cancelled, completed, or
legacy unverified entries are never swept into automatic catch-up sends.

- `--owner master|xi|both`
- Rejects times in 23:00-07:00 unless `--allow-night`
- Deduplicates by owner/date/time/title in `memory/reminders.json`
- Creation is journaled under the same lock used by reminder maintenance.
  `creating` / `uncertain` means reconcile remote timers before retrying;
  `both` retries only a recipient whose creation definitely did not start.
- `reminder_admin.py --list` shows both index status and receipt state.
  `--gc` preserves the recovery window, then marks upgraded entries `missed`;
  older entries become `delivery_unverified`, not presumed sent or unsent.
- `--mark ... --status sent` requires an accepted delivery journal record.
- Requires cc-connect to be running (it uses the local API socket)

## Deploying the dispatcher and upgrading existing timers

Copy `reminder_send.py` together with `add_reminder.py` and
`reminder_admin.py`. Existing prompt-based timers do not automatically adopt
the new sender, and the dispatcher only scans `dispatch_version=1` entries.

1. Back up the reminder index and `cc_data_dir/timers/jobs.json`. Inspect
   `reminder_admin.py --migration-plan`: every future scheduled entry must
   match a pending timer by ID, project, exact session, stable bot account,
   and local scheduled minute. Fired or uncertain timers are rejected.
2. Disable the watchdog and stop this cc-connect instance. Run
   `reminder_admin.py --migrate-stopped`. It independently checks that the
   configured service executable is not running, validates the entire plan,
   replaces only each matching timer's prompt with a muted deterministic
   command, and upgrades the matching index entries. Other timer fields and
   history remain intact. If either write fails, keep the service stopped
   and rerun or restore both files from the backup before restarting.
3. Reuse the existing reminder-maintenance cron, or install one muted native
   cron that runs every minute. Obtain its command with
   `reminder_admin.py --dispatcher-command`; it executes
   `reminder_send.py --due`. Keep GC as a separate daily maintenance action.
   A one-shot timer alone cannot recover a known-unsent lock/budget block.
4. Restore the service/watchdog and verify the future timer commands, the
   cron schedule, and its receipt journal. Preserve past uncertain or ended
   entries for inspection rather than upgrading them for automatic replay.

On Windows the maintained timer uses `powershell.exe -NoProfile
-ExecutionPolicy Bypass -Command`. Generated commands use PowerShell's `&`
and single-quoted literal arguments, with the Python exit code propagated.
The offline shell test exercises this exact entry, including paths containing
spaces, an apostrophe, `&`, and `$`.

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
- Timer fired but no message — inspect the delivery journal and maintenance
  cron. A timer firing or a model finishing is not a send receipt. `blocked`
  may recover within its window; `uncertain` requires reconciliation.
- `消息发送过快，请稍后再试` — cc-connect's incoming per-session rate limit
  (default 20/60s), not the model. Set `[rate_limit] max_messages = 0` for a
  trusted single user, or wait.
- `send budget exhausted` — local cc-connect guard; v1.5.0 counts replies too. Use `burst_limit=20` and `burst_window_secs=60` per Weixin platform. Gateway rejections must be handled separately; do not repeatedly retry.
