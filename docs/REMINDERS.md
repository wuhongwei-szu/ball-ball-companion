# Reminders and proactive care

## One-shot reminders

Create a reminder only on an explicit request. A future plan or a request to
draft a notice is not itself permission to create a timer. Resolve the target,
calendar date and ambiguous AM/PM first; inspect the resulting timer before
confirming success.

```bash
python -X utf8 tools/add_reminder.py \\
  --owner master --date 2026-11-10 --time 07:30 \\
  --title "体测" --note "带水、运动鞋，别迟到"
```

The tool uses cc-connect's timer with a stable account binding. Ordinary quiet
hours are 23:00–07:00; explicitly requested exceptions use `--allow-night`.
Changing a reminder requires reconciling its actual timer ID, not merely editing
notes. Preserve unrelated timers and execution markers. An uncertain creation
or send result must be investigated before retrying.

## Per-recipient care

The current `per_recipient_v1` scheduler plans one opportunity for master and
one for xi. Times are randomized within 08:30–21:30 with at least two hours
between them. A late start can leave fewer slots; expired opportunities are not
backfilled. Existing same-day and legacy plans are retained instead of rerolled.

Each opportunity evaluates only its recipient. Recent conversation, a request
not to be disturbed, repeated unanswered outreach, unclear identity, stale
context or an uncertain previous send can suppress it. An opportunity does not
guarantee a message.

`chat_burst.py --proactive` permits at most two outgoing items, including an
optional sticker. Each recipient has a separate default budget of four proactive
messages per local calendar day and a five-minute minimum gap. The daily count
resets at midnight; the gap does not. This is not a rolling 24-hour allowance or
an official iLink limit. Server throttling such as `ret=-2` still applies.

## Configuration

- `WINDOW_START_MIN` / `WINDOW_END_MIN`: active planning window.
- `MIN_GAP_MIN`: spacing between opportunities.
- `proactive_daily_limit` / `proactive_min_gap_seconds`: local sending limits.
- Stable `master_account_id` and `xi_account_id` bindings are required.

Do not use manual test switches on live accounts without explicit send
permission. Repository tests use synthetic state and mocked transport.

## Verification

Timer creation, task processing, API acceptance and recipient receipt are
separate outcomes. A stored response or `NO_REPLY` alone does not prove delivery.
For `context_token` expiry, the recipient may need to message the correct bot.
For a local guard or gateway rejection, stop and inspect the specific failure;
do not relogin, switch transports or replay automatically.
