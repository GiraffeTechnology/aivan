# GPM component HTTP regression

`tests/integration/test_gpm_provider_http.py` exercises the existing advisory-only
GPM API through Aivan's real consumer, with selected real service processes.
It does not implement pricing, approve a commercial action, send messages, or
claim the complete inquiry-to-order workflow is accepted.

The fixture performs actual provider Alembic migrations on a new temporary
SQLite file, creates only installation/control tenant identities using the
shipped installer pattern, and creates business records through authenticated
Data API calls. A source-quote digest binds the explicit synthetic English quote
used before formal quotation persistence. No private/customer data is required.

Run in a disposable Linux development environment. Set
`AIVAN_GPM_COMPONENT_RUNTIME` to an extracted, hash-verified selected package
containing `runtime/bin/python3` and `provider-assets/giraffe-db/alembic.ini`.
Configure a real canonical-language service with `GIRAFFE_LANGUAGE_SKILL_URL`
and a real GLTG API with `GLTG_API_BASE_URL` and its authorized service credential.
Do not put credentials in command arguments or evidence.

Set these flags **before starting pytest**, so autouse unit fixtures do not
replace actual consumer transports:

```sh
export RUN_GLTG_INTEGRATION_TESTS=1
export RUN_GPM_INTEGRATION_TESTS=1
export RUN_LANGUAGE_SKILL_INTEGRATION_TESTS=1
python -m pytest tests/integration/test_gpm_provider_http.py -q
```

The canonical-language module must be genuinely configured, not disabled or
mocked. This English fixture tests actual canonical validation, not multilingual
neural translation. GLTG performs its real numeric calculation with private
evidence explicitly disabled. GPM uses the supported API-disabled advisory
mode, comparing only supplied totals; it does not claim Qwen/model inference.

Checks include tenant/authentication isolation, actual GLTG provenance passed
to GPM, durable packet readback, effective idempotent replay, changed-payload
conflict, no dispatch, both-service restart recovery, and DB-down fail-closed
behavior without successful memory degradation. Approval/rejection features
remain explicitly disabled in the advertised GPM advisory path.

No selected runtime means this optional component test is skipped, **not passed**.
An enabled test with incomplete live configuration fails. Record exact consumer,
provider, GLTG and language revisions and the result actually executed. The
temporary SQLite result is not MySQL, target deployment, durable GLTG evidence
persistence, independent model acceptance, or full product/UI acceptance.
