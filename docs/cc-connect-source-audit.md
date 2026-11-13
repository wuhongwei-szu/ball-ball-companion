# Maintained cc-connect source audit

## Verified provenance

- Official upstream: https://github.com/chenhg5/cc-connect
- Tag: v1.5.0
- Commit: 17c61062c2f9ce9bcdd45a2082e491f9743a2770
- The earlier 460-file local maintenance baseline matches this tag after CRLF
  normalization, except core/engine.go and four generated web/dist assets.
- The engine difference is a configurable comma-separated list of users whose
  busy-session queue acknowledgements are suppressed. No account IDs are
  embedded in that implementation.
- Seventeen later account-routing, timer and shared-memory source changes match
  the retained build manifest. The original shared-memory release executable SHA-256 was:
  4b7a28f3fa5236484e0d588a35f7cb3f9fe7de7211950d022321c978c94175f7.
- Retained full source digest:
  8da078ef94f1cd42e651ff51edbbc00faccd55a5469be5d5d96f28b2c514f06b.

## Publication boundary

The official tag's npm/package.json declares MIT and names chenhg5 as author,
while that tag contains no LICENSE, COPYING or NOTICE file. This audit does not
assume the npm wrapper's declaration resolves all Go source and generated web
asset redistribution notices. No complete upstream snapshot or compiled web
assets are copied into this repository.

A small patch against the exact tag, with upstream attribution and the confirmed
applicable license notice, is the preferred follow-up. Preserve the retained
local source until those notices and generated-asset provenance are resolved.
Do not invent an upstream copyright statement or silently label all source as
this application's license.

## Review limits

A targeted scan of all 17 changed source files found no known credential
patterns, private account identifiers, personal names or user-home paths.
This is not a guarantee that all 467 retained files and bundled frontend assets
are suitable for publication. No Go build or test was rerun during this audit.
The previous release records report focused tests, not a fully passing Go suite.

The Python memory bridge requires an absolute python executable path in private
config/shared_memory.json as well as the project and subject bindings. The
example now includes this required field. It is not a deployment instruction.

## Current runtime receipt

Later usage and original-voice changes are tracked in the maintained deployment.
The current application release receipt records the actual executable, source
archive and rollback location. The original-voice patch only changes Weixin
attachment handling; it preserves the existing engine and agent backend.
See `deploy/cc-connect-voice-attachment.patch` and `REFACTOR_PLAN.md`.
