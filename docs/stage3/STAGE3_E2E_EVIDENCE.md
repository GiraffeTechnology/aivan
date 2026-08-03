# Stage 3 E2E evidence

Date: 2026-08-03

Five consecutive Gateway runs completed successfully. Each run executed 16
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

Result: `5/5 PASS`, `80/80 assertions`, `0 failures`.

The test server is deterministic and local. It uses no business records,
channel credentials, LLM keys, passwords, or external APIs. Approval and
rejection tools call AIVAN Core endpoints only; the plugin has no direct send
channel and cannot bypass the server-side human approval gate.

For CTYun deployment, any access to IP addresses outside China must use the
existing Singapore bridge (`Aivan` to `abcdyi-sin`). Stage 3 does not add a
direct CTYun-to-GitHub/npm path and does not embed bridge credentials.
