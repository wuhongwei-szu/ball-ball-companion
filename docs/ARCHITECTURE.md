# Architecture

## Components and public scope

- cc-connect owns platform sessions, routing, timers and cron jobs. The maintained
  build adds account/timer/memory changes beyond upstream v1.5.0. See the
  [source audit](cc-connect-source-audit.md); a stock npm package is not equivalent.
- The local agent uses runtime/persona templates and Python tools. Private rendered
  prompts, accounts, sessions, memory, media and credentials stay outside this repo.
- Python tools cover sending, capture, structured memory, reminders and health
  checks. The candidate module layout is in [maintenance-candidates.md](maintenance-candidates.md).

## Identity and data flow

1. An inbound message is bound to a platform account and session. Both entrances
   share one persona, while speaker, subject, privacy and preferences remain distinct.
2. `master_account_id` and `xi_account_id` must be unique stable account matches.
   Platform list order and `xi_platform_index` are not identity bindings.
3. A simple response can use the agent's normal response path. Tool-driven bubbles
   use `chat_burst.py` / `send_msg.py` and end with `NO_REPLY` to avoid duplication.
   Ordinary bursts allow at most six items; proactive bursts allow two; an image
   counts as one. Lossless bodies use explicit UTF-8 JSON stdin.
4. The xi media helper chooses cc-connect for the active bound xi session, or its
   explicit direct route otherwise, before attempting delivery. Unknown results
   never cause a transport fallback. API acceptance is not recipient confirmation.
5. Capture uses session-scoped checkpoints and prefix continuity. It captures only
   proven-new user records, withholds uncorrelated assistant records and is not a
   historical backfill operation. Outbound tools retain their existing raw/recent
   recording behavior; those records are not a universal delivery ledger.
6. Candidate memory exclusions gate exact sources in ingest, learning, recall and
   capture. The consolidation exporter admits eligible original sources, grounded
   facts and reviewed historical blocks, with explicit bounded-coverage metadata.
   Deploying the corresponding prompt is separate; arbitrary direct file writes
   and existing model context are not technically isolated by these hooks.
7. Care planning creates at most one opportunity per entrance per day, with random
   times and recipient-specific context checks. Local proactive counters are per
   recipient/local calendar day, not a shared rolling 24-hour allowance.

## Configuration and runtime state

`config/bot.config.json` holds private paths, configured session references,
labels and stable account IDs. Runtime token/context data is derived from the
existing cc-connect configuration and session files. Session labels such as s1/s2
are not universal permanent identities; inspect actual mappings on rotation.

`config/shared_memory.json` holds the separate structured-memory identity
bindings and absolute Python path. Candidate `config/memory_exclusions.json`
holds reviewed source/block metadata. Both are private and ignored. Missing or
invalid exclusion configuration fails closed; the empty public sample is not a
real exclusion policy.

## Timers, rollout and rollback

Recurring jobs and their schedule are deployment configuration, not enabled by a
repository clone. One-shot reminders require an explicit user request and actual
timer reconciliation. Consolidation must not opportunistically create reminders.

Publishing source does not deploy it. Recheck production baselines and service
identity before a coordinated rollout. Preserve current history, timer execution
markers and capture cursors during rollback. See [maintenance-candidates.md](maintenance-candidates.md)
and [REMINDERS.md](REMINDERS.md) for verification limits.
