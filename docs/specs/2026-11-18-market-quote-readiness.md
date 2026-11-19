# Market quote readiness after pooled login

A successful MT5 login can precede the first usable symbol tick. Market orders
must use a finite, positive broker bid/ask, without requiring or inventing a
signal entry price. Wait up to two seconds for that tick, bounded by the pooled
execution deadline. Preserve the existing validation, protection levels,
idempotency, pre-trade checks and single order submission.

If no quote arrives, return HTTP 503 with `connection_error` and
`submitted: false`. This explicitly means no broker order was sent. Plane may
allow an identical keyed retry of this pre-submission failure. Ambiguous broker
outcomes retain their existing quarantine and reconciliation requirements.

Verification: deterministic quote-readiness tests plus HTTP order tests for
zero-to-valid quotes, permanent missing quotes, preserved SL/TP and same-key
retry after a failure before submission. No live order is needed for these tests.
