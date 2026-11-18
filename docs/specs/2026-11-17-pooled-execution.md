# Pooled execution

`MT5_POOL_MODE=1` opts a gateway into private, serial execution managed by Plane.
One process and one account are active at a time. Dedicated mode remains the default.

The worker first authorizes a bootstrap account using the existing startup policy.
Readiness reports `pool_worker: true` only after authorization. Bootstrap places no
trades. Plane keeps saved identities separate from containers and owns admission,
durable idempotency, reservations and recovery.

`POST /internal/execute` requires a configured API key and accepts login, server,
password, HTTP method, allowlisted path, operation body and an absolute UTC deadline.
The execution lock spans login, identity verification and dispatch through existing
validation, kill-switch and trading handlers. Raw account/trading access is denied
in pool mode. Credentials never appear in responses.

Broker identity is verified before dispatch and at serialized data/submission
boundaries. Expired requests cannot initiate broker submission; an in-flight broker
call can finish after the deadline. Reconnect uses operation credentials rather
than bootstrap credentials. Session credentials and account-specific caches are
cleared afterward; IPC cleanup failure still releases the execution lock.

Plane handles transport loss after a mutation as an unknown outcome, with worker
quarantine and explicit broker reconciliation. A busy reservation never expires
into automatic replay. Changing a key cannot bypass an unresolved account operation.

Live validation covered same-account demo reads on an initialized worker. A fresh
unsigned-in terminal timed out at IPC attachment, so authorization completes before
admitting the worker. Two-account and cross-broker switching still require validation
with two demo accounts. Never treat an unvalidated switch as proof of broker identity.
