# cc-connect queue-safety candidate

This is a focused patch, not a complete cc-connect source distribution or binary.
The upstream project is https://github.com/chenhg5/cc-connect, tag v1.5.0,
commit 17c61062c2f9ce9bcdd45a2082e491f9743a2770.

Apply only after checking the maintained source baseline described in
[the source audit](../../docs/cc-connect-source-audit.md). That baseline includes
account-routing, timer and memory-bridge changes beyond the upstream tag.
The patch is not asserted to apply cleanly to an unmodified upstream checkout.
Do not replace a running maintained build with a stock npm release.

## Changes

- Add a hashed, session-scoped message reference to admission diagnostics.
- Record queue-full rejection and the notification result separately.
- Tell the sender clearly that a full-queue message was not queued.
- Keep accepted messages FIFO; do not retry uncertain notifications.
- Include synthetic Go tests in the patch, including image bursts at limits 5
  and 10, rejection behavior, reference stability and received/admission correlation.
- Provide an optional queue-limit configuration fragment. It is not automatically applied.

The added diagnostics avoid adding raw message content or identifiers. Existing
upstream logging elsewhere is not covered by that claim.

## Verification and status

The isolated candidate audit recorded 18 focused queue checks, go vet for
core/config and a default build passing. These Go checks were not rerun by this
application-repository integration. Full upstream regression, real-message
end-to-end behavior and production restart are not verified here.

This branch is a review candidate. Publishing it does not deploy the patch.
No executable, account configuration, message history or production log is included.

## Attribution and distribution boundary

The patch contains small context hunks from the upstream/maintained sources and
new maintenance changes. It does not relabel upstream source or generated web
assets as this application's MIT-licensed work. The upstream tag's complete
source/asset notice reconciliation remains open as documented in the source audit;
no complete upstream snapshot or generated assets are redistributed here.
