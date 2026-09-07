# G2-A remediation traceability

| Audit finding | Implementation | Regression evidence | Acceptance state |
|---|---|---|---|
| G2A-P0-01: tenant-only HMAC can self-assert approver | `auth.py` labels the profile `tenant_hmac`, ignores caller actor/role headers for that profile, and denies all decision capability before mutation | `test_tenant_only_hmac_cannot_self_assert_approver`; packet and receipt remain unchanged | Locally passed; independent audit required |
| G2A-P1-01: provider 404/409 rewritten to 503 | `giraffe_db_client.py` accepts only versioned status/code pairs for packet-not-found, already-decided, and idempotency-conflict; all unknown envelopes fail closed | `test_decision_adapter_maps_versioned_provider_errors`; `test_decision_adapter_fails_closed_for_unknown_provider_errors` | Locally passed; real provider implementation remains out of scope |
| G2A-P1-02: dot-segment/path escape | Strict ASCII outbound ID grammar is enforced before transport; URLs are built with `httpx.URL.copy_with` | 12 malicious tenant/packet ID cases assert zero transport calls | Locally passed; CodeQL rerun required |
| G2A-P2-01: stale non-production cache after durable decision | Durable atomic proof now refreshes the local cache only after successful validation | `test_durable_decision_refreshes_nonproduction_cache`; existing failure/concurrency tests remain green | Locally passed |

Out of scope and unchanged: giraffe-db implementation, database schema, migrations, G3-G6 product work, deployment, and merge authority.
