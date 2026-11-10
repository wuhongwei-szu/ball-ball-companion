# Maintenance candidates (2026-11-11)

This branch contains reviewable source candidates based on application commit
`d2f4f440c1ab65a4dc3573064e393f6f545a58e3`. Repository publication is not a
production deployment. Existing account bindings, capture continuity rules,
midnight spacing and conservative delivery handling remain in place.

## Modules

- **Text transport:** `tools/text_input.py` validates UTF-8 JSON input for
  `send_msg.py`, `chat_burst.py` and the direct `send_xi.py` helper.
  Dollar signs, quoting, actual/literal newlines, emoji and leading option-like
  text survive without shell interpolation. Existing positional arguments,
  account guards, quotas and no-blind-retry behavior remain supported.
  See [TEXT-TRANSPORT.md](TEXT-TRANSPORT.md).
- **Source exclusions:** `tools/memory_exclusion.py` checks exact speaker/source
  pairs at ingest, learning, recall and capture. Legacy blocks use a relative
  path and exact block hash. Known ambiguous files can be scoped for quarantine;
  future messages with different source IDs are not semantically banned.
- **Consolidation input:** `tools/memory_consolidation_input.py` is read-only.
  It exports eligible recent source statements, grounded active facts and
  explicitly reviewed historical blocks. Independent record/byte budgets keep
  the three classes represented. Coverage reports are bounded views, not proof
  of complete history. Absent output must not erase existing memory.
- **Prompts:** public templates separate persona from identity, memory and tool
  rules. They avoid automatic reminders from casual future plans, require exact
  time clarification when needed, preserve per-person preferences and distinguish
  API acceptance from recipient receipt. Rendering and enabling them is separate.
- **Queue diagnostics:** [a small cc-connect patch](../patches/cc-connect/README.md)
  records admission/rejection and makes queue-full loss visible. It is not an
  application Python change or a mirrored bridge source tree.

## Required private configuration

`config/memory_exclusions.example.json` is deliberately empty. Copy it locally
only as a schema starting point, then populate independently verified metadata in
`config/memory_exclusions.json`. Never commit that private file. An empty example
is not evidence that any actual source has been excluded.

Missing or invalid exclusion configuration fails closed in affected entry points.
Install and validate the configuration and supporting module before enabling the
changed tools in a coordinated maintenance window. Do not copy these files one
by one into an active deployment or bypass missing configuration with an empty
policy merely to make the service start.

Source IDs from structured messages and capture checkpoints use different
namespaces. Bind each applicable path independently. Legacy hashes refer to the
exact pre-normalization block, not a whole file. Reviewed historical evidence
must never be promoted to a current fact solely because it was reviewed.

## Limits

This is not a universal forgetting or deletion boundary. It does not remove
original chats or existing database rows. Direct file/SQLite writes, existing
model-session context, unbound replays with new platform IDs, other capture
callers and unreviewed historical material outside explicitly scoped files can
bypass these hooks. Concurrent policy updates and writes are not transactional.
A controlled consolidation output writer and OS/tool-level isolation remain open.

## Verification

The source-only audit recorded 7 lossless-transport tests, 17 exclusion/exporter
tests and syntax checks for 9 candidate Python files on Windows. Repository
integration ran 54 existing/new synthetic tests on Windows with Python 3.14.0a5:
53 passed and one pre-existing legacy-marker false positive remained an expected
failure. Compileall for tools/scripts/tests and the repository secret scan passed.
GitHub CI separately runs Windows/Python 3.11; consult the PR's exact-commit check.

Tests use synthetic temporary state and mocked transport. The lossless suite
uses only an echo subprocess for its real PowerShell encoding check. Historical
transport fixtures under `tests/fixtures/lossless_baseline/` are pinned to the
previous public application baseline for parity assertions, not runtime imports.

No live model calls, WeChat sends, production memory reads or service restart
are part of repository tests. Focused Go audit results are distinct from a full
upstream regression run.

## Deployment and rollback

Before any rollout, recheck each production baseline hash and resolve newer
changes rather than replacing them. Back up changed code/configuration, identify
the exact service and watchdog, and use the separately authorized maintenance
procedure. Roll back only this change's code/configuration; never rewind message
history, capture cursors, timer execution markers or existing memory state.
Observe natural traffic after rollout and report processing, API acceptance and
recipient confirmation as separate verification levels.
