# Application source reconciliation (2026-11-07)

This snapshot recovers the reusable Python/PowerShell tools currently installed
in the maintained deployment. It does not deploy anything or replace private
configuration, prompts, accounts, conversations, assets, or executable binaries.
Only the hardcoded partner display name in companion_memory.py is generalized.

## Required configuration

- Populate master_account_id and xi_account_id with distinct stable bot account
  IDs. List order is not an identity binding. Missing/ambiguous bindings fail
  closed before sending or creating timers.
- Shared attributed memory requires private config/shared_memory.json, using
  shared_memory.example.json as a schema template. Do not commit real bindings.
- The memory bridge also requires the maintained cc-connect build; copying the
  Python module alone does not install the engine-side inbound metadata bridge.
- Direct voice sending is experimental and needs cryptography. Sticker image
  operations may need Pillow. Existing voice tooling dependencies still apply.

## Preserved behavior

Account-bound sending/timers, conservative capture across session rotation,
shared memory with attributed/versioned facts, explicit confidentiality, sticker
administration/review/feedback, and direct voice tooling are included. Capture
is not a historical backfill command. Unknown delivery results must not trigger
an automatic retry through another transport.

## Verification and remaining work

Python syntax and repository secret scan passed. Thirteen synthetic shared
memory tests passed on Windows, without production configuration or sending.
This is not an end-to-end delivery test or a complete service regression pass.

The two small Python repairs were subsequently deployed and synchronized:
capture now recognizes generated care/reminder templates, and the proactive
minimum interval survives midnight. The original legacy marker substring
false-positive remains documented as an expected test failure. Unlimited-budget
semantics are unchanged; the old audit archive's broader budget refactor was
not deployed. Tests use synthetic state and never import private configuration.
The installed cc-connect build has additional Go account-routing, timer and
memory-bridge changes. Its maintained source is retained locally. This commit
does not claim that upstream Go sources or the installed binary are mirrored
here; those require a separate source/licensing/build reconciliation.
