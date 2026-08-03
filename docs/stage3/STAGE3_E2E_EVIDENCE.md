# Stage 3 E2E evidence

Date: 2026-08-03

Five consecutive Gateway runs completed successfully after review fixes. Each run executed 18
assertions and covered:

1. exact six-tool enumeration;
2. optional approval/rejection metadata;
3. Agent Harness registration;
4. non-trade rejection and explicit pass-through without an AIVAN call;
5. trade-sourcing acceptance and reply;
6. direct invocation of all six tools;
7. one controlled retry after a transient 503;
8. stable idempotency header/body key;
9. user-visible structured error mapping.
10. stable Harness message idempotency across redelivery;
11. preservation of HTTP-200 fail-soft replies for the end user.

Result: `5/5 PASS`, `90/90 assertions`, `0 failures`.

The test server is deterministic and local. It uses no business records,
channel credentials, LLM keys, passwords, or external APIs. Approval and
rejection tools call AIVAN Core endpoints only; the plugin has no direct send
channel and cannot bypass the server-side human approval gate.

This harness validates the plugin contract, not production participant identity
binding. Stage 3 supplies one static service identity from process environment
variables. It does not prove that individual WeChat participants are mapped to
trusted AIVAN actors or roles; that production-mode binding is explicitly deferred
to Stage 4. The bridge must not be cut over for multi-participant role attribution
until that requirement is implemented and tested against the real Core.

For CTYun deployment, any access to IP addresses outside China must use the
existing Singapore bridge (`Aivan` to `abcdyi-sin`). Stage 3 does not add a
direct CTYun-to-GitHub/npm path and does not embed bridge credentials.
