# Memory system

This branch adds review candidates, not an automatic production rollout. See
[maintenance-candidates.md](maintenance-candidates.md) for exact-source exclusions,
private configuration, bounded coverage and remaining bypass paths.

## Files

| Path | Purpose |
|---|---|
| `memory/companion.sqlite3` | Attributed source statements and versioned facts, private |
| `memory/raw/s1|s2/YYYY-MM-DD.md` | Redacted captured/outbound records, not a complete delivery ledger |
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

1. **Capture:** the deployment's recurring capture task uses session-scoped
   checkpoints and continuity checks. Proven-new user records can be captured;
   uncorrelated assistant history is withheld. It is not a backfill command.
2. **Send recording:** existing send tools append outgoing text to raw/recent
   records. Stored text does not itself prove recipient receipt.
3. **Structured memory:** stable identity bindings keep speaker and subject
   distinct. Corrections version facts instead of overwriting original sources.
   Private/restricted material is not automatically shared between entrances.
4. **Candidate exclusion:** exact speaker/source pairs are checked during ingest,
   learning, recall and capture. Legacy matches use exact path/block metadata.
   The public example is empty; actual reviewed bindings stay local.
5. **Candidate consolidation:** the read-only exporter provides bounded eligible
   source statements, grounded facts and reviewed historical blocks. The template
   uses only that input, stops on error/empty output, preserves unrelated state
   and creates no reminders. Enabling it in the real cron is a separate operation.
6. **Recall:** use the source-aware search tool for past details, retain dates and
   attribution, and do not upgrade old statements into current facts. Missing
   results or truncated exports do not imply deletion or justify guessing.

The exclusion hooks do not erase original records, universally block direct
reads/writes, remove existing model context or identify unbound replays with new
IDs. Do not describe this candidate as complete forgetting or deletion.

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

Both entrances share one persona and common experiences, not unrestricted access
to each other's private conversations. Keep per-person preferences, source
attribution and confidentiality boundaries. Session labels s1/s2 are deployment
references, not immutable identities; review mappings after session rotation.
