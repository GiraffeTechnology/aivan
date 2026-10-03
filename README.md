# Aivan — Giraffe Agent's Digital Trade Assistant

`Python 3.11+` | `Inquiry → Quotation → Order Confirmation` | `DB-backed workflow` | `Human review`

Aivan is the frontend application of Giraffe Agent for inquiry, quotation and order confirmation. It helps businesspeople structure requirements, find and assess suppliers, compare responses, use lead-time/path reasoning, prepare messages and confirm orders with human control.

abcdYi is the apparel/textile industry application of Giraffe Agent and its frontend calls Aivan. MyAivan is Aivan's web version, maintained on the permanent `myaivan-web` release branch. Do not merge that branch into `main`.

## Product and acceptance documents

- [Aivan product requirements](docs/AIVAN_PRODUCT_PRD.md)
- [MyAivan first web iteration](docs/MYAIVAN_WEB_PRD.md)
- [Observable acceptance criteria](docs/ACCEPTANCE_CRITERIA.md)
- [Source reconciliation and superseded interpretations](docs/PRODUCT_SOURCE_RECONCILIATION.md)
- [Code preservation inventory](docs/SCOPE_PRESERVATION_INVENTORY.md)
- [Repository instructions](AGENTS.md)

These documents define the reconciled delivery target. They do not claim that the current branch, a candidate PR or a deployed service has completed it. Legacy issues and stage reports are evidence about their own revisions; they do not independently authorize extra requirements.

## Component boundary

| Component | Responsibility |
| --- | --- |
| Aivan | Shared inquiry, quotation, human review and order-confirmation frontend workflow |
| MyAivan | Conversation-first web version of Aivan; separate release line, shared business truth |
| abcdYi | Apparel/textile industry rules and full industry order execution; frontend calls Aivan |
| OpenClaw-Aivan | IM/email access through the OpenClaw gateway/runtime and account-connectivity layer |
| GLTG | API-invoked lead-time and feasibility calculation |
| GPM | API-invoked quotation/pricing guidance through its API contract |
| Private-domain DB | Dynamic business history and process system of record; giraffe-db or a compatible user DB |
| giraffe-language-skill | Dynamic translation before non-English input enters workflow and for requested localized output |
| Human | Outbound-message review and consequential commercial decisions |

The product is not limited to a monitoring/takeover control plane. No separate formal-contract record, signature or version check is a mandatory extra prerequisite before production.

## Data and language

Aivan reads facts and process state from the private-domain DB and persists workflow changes there. It must resume correctly after a conversation switch or restart. Chat/LLM context and browser memory are not business truth. A DB-derived request-context object is allowed.

The DB provider is replaceable through its compatible API/adapter. The two designated simulated databases, generated from real local data, are valid acceptance sources. Exercise actual application code, selected APIs, writes/readback and recovery; do not confuse legitimate simulated datasets with fake service responses or skipped integration steps.

Standard English is the language of work and interaction. Non-English input is dynamically translated through `giraffe-language-skill` before business workflow. Non-English output also uses that module. Except for enterprise/user profile information, the DB must not store non-English content, including raw-message, audit or metadata copies. See [the language and storage rule](docs/GIRAFFE_INTERNAL_WORKING_LANGUAGE.md). Existing data is inventoried for a safe authorized migration, not deleted by this documentation change.

## User workflow

1. Receive an inquiry, supplier response, supported file/image or operator instruction.
2. Show structured requirements, known facts and missing-field questions.
3. Read suppliers, products and history from the configured private-domain DB.
4. Prepare supplier inquiries and compare actual responses using the applicable GLTG/GPM APIs.
5. Present quotations/options and risk notes for human review, rejection or revision.
6. Carry out the explicitly authorized channel action with truthful status.
7. Confirm the selected order and persist its state and audit evidence.

Return the actual number of available options; never fabricate a third supplier. Preserve supplier-stated facts separately from inference and forecasts. Model percentiles are estimates, not an unmeasured delivery guarantee.

## MyAivan first web iteration

The required UI is **Welcome → Start Working → Conversation**. The conversation page has a top message stream, middle generated-draft review and bottom text/paste/file/image input. User messages align right and Aivan messages left. File/image input must work; voice transcription may be an honest placeholder. Case Markdown backup is required.

Draft actions are Copy, Send by Email, Mark as manually sent and Reject. All IM channels, including WeChat, WhatsApp, LINE and Wangwang, use review/copy/manual-send/confirmation. Email uses explicit confirmation and a configured OpenClaw-Aivan adapter; unavailable email shows a clear manual-copy fallback. Mock, failed or uncertain delivery is never shown as actual success.

The original five-consecutive-run, 20-case UI checks remain required. A first-UI pass does not claim that all full-product, industry-lifecycle or deployment work has passed. Supporting operations screens do not replace the conversation experience.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/GiraffeTechnology/aivan.git
cd aivan
./scripts/bootstrap_local.sh
```

Or prepare the existing local development profile manually:

```bash
cp .env.example .env
uv sync
uv run aivan init
```

For MyAivan work, use its permanent branch and target web PRs to `myaivan-web`. These commands are local development instructions, not authorization to replace a running service or its data.

## Run locally

```bash
uv run aivan serve
uv run aivan demo
```

The existing local app route is `http://127.0.0.1:8765/app`. The demo uses explicit mock providers. A successful mock demo is useful smoke evidence but does not prove the real DB/GLTG/GPM/channel integrations or the required first-web-iteration UI.

## Repository checks

```bash
uv run pytest -q
uv run python scripts/validate_clawhub_aivan_plugin.py
uv run python scripts/run_aivan_openclaw_plugin_smoke_test.py --offline
uv run python scripts/run_aivan_openclaw_full_check.py
uv run python scripts/run_private_domain_rfq_e2e.py
uv run python scripts/run_aivan_e2e.py
```

Check each script's selected profile and prerequisites. The private-domain offline runner and mocked transports do not establish real API acceptance. Record actual executed steps; a skipped step is not a pass. Keep CI green before merge, and report configuration/scan availability separately from product functionality.

The current [security scan policy](docs/SECURITY_SCANNING.md) documents the independent security change: Semgrep source checks, offline OSV dependency matching, zizmor Actions checks, retained Bandit/npm audit, and their coverage limits. These scans are not equivalent to CodeQL security-extended. Preserve actual findings, scanner failures and reports; passing these checks does not establish product acceptance.

## OpenClaw integration

The bridge lives in `integrations/openclaw-aivan-plugin/`. Its plugin ID is `openclaw-aivan`; the package is `@giraffetechnology/openclaw-aivan`. The entry registers an agent harness. Inbound IM/email is normalized into the shared event contract and submitted to `/invoke`; existing aliases include `/api/openclaw/events`, `/api/skill/invoke` and `/api/rfq/create-from-event`.

`skills/aivan-trade-salesperson/SKILL.md` routes trade intent to the plugin. The event's case/project and participant context distinguish buyer-side inquiry, supplier-side reply and operator commands. The transport does not independently authorize a business action or declare delivery.

Account credentials remain with the authorized connectivity/configuration boundary. Aivan keeps account metadata, never platform passwords, cookies or session tokens. Platform trust does not imply supplier trust or waive outbound review.

## GLTG and GPM integration

GLTG is a standalone API dependency. Existing configuration includes:

```bash
GLTG_API_BASE_URL=http://localhost:8090
GLTG_API_TIMEOUT_SECONDS=30
GLTG_API_VERSION=v1
```

The selected version determines the estimate/simulation, path and reforecast contract. See [the GLTG integration requirements](docs/GLTG_BEHAVIORAL_STATISTICAL_MODEL_ITERATION_PRD.md). Do not silently calculate replacement lead times locally. GPM quotation/pricing guidance and durable decisions likewise use their chosen API/provider contract, with source, tenant and persisted process-state evidence.

Full DAG simulation, optional schema expansion and long-term calibration are later model work, not default prerequisites for a usable first iteration.

## Configuration and existing runtime behavior

The existing local profile includes:

```bash
AIVAN_ENV=local
AIVAN_HOST=127.0.0.1
AIVAN_PORT=8765
AIVAN_DB_URL=sqlite:///./data/aivan.db
AIVAN_REQUIRE_HUMAN_APPROVAL=true
OPENCLAW_MOCK_MODE=true
```

See `.env.example` for supported settings. Provider choice and runtime configuration must satisfy the actual selected data contract; a local filename is not the product's mandated system of record.

Production is intentionally stricter:

- Authentication must use trusted server-side identity and tenant binding; request-body role or tenant strings are not authority.
- A public browser profile needs safe sessions, exact CORS and protection of credentials and data.
- In the existing main-branch dependency-probe implementation, the giraffe-db probe verifies `/healthz` readiness and the authenticated `/api/data/schema-version` response against its selected contract; provider response tenant echo is not required by that endpoint's current response shape.
- Report actual selected-provider compatibility and failed dependencies honestly. The current runtime policy and probe configuration are implementation facts; they do not make a particular provider instance, legacy product-role string, static locale bundle or named stage an independent product requirement.
- A state-changing operation requires the appropriate committed DB result and audit/idempotency semantics; dependency failure must not produce false success or fake memory persistence.

In production, protected data and external actions must remain safe. If a legacy guard prevents a now-required compatible provider or product flow, record the mismatch and fix it in an authorized scoped code change while preserving its safety purpose. This documentation proposal does not disable guards, change configuration or claim such a fix is implemented.

No README or passing preflight authorizes deployment, migration, production writes, outbound messages, DNS/proxy changes or service restarts. Apply environment-specific operational restrictions when that environment is actually involved; do not turn a full operational program into an unrelated functional-acceptance gate.

## Preservation and status

Useful code, tests, operational protections and assets are retained. Scope-expanded or unconfirmed work is inventoried and frozen at recorded revisions rather than deleted or silently activated. Runtime gaps and non-English-content migration require separate scoped work; this cleanup changes documentation only.

For any completion report, identify the exact candidate, tested scope, DB source/provider, APIs, actual results and remaining limitations. Documents, PRs, historical evidence and green aggregate jobs do not establish current product acceptance by themselves.

## License

See `LICENSE`.

## GPM quote guidance and persistence

Aivan sends the selected quote, currency, authenticated actor, and GLTG result reference to the independently served GPM API. The selected provider must preserve these fields and return them on readback before the result is accepted. Provider discovery is compatibility evidence; a capability label alone does not prove persistence.

Start the standalone service with deployment-managed authentication, model, and provider settings:

```sh
uv run python -m aivan.gpm.server --host 127.0.0.1 --port 8080
```

The controlled HTTP acceptance runner uses isolated synthetic inputs and does not start services, apply migrations, or print secrets:

```sh
uv run python scripts/run_gpm_giraffe_db_http_acceptance.py --phase full
uv run python scripts/run_gpm_giraffe_db_http_acceptance.py --phase readback --packet-id <saved-packet-id>
```

It verifies trusted tenant/actor headers, quote and currency identity, model results, GLTG lineage, provider readback, replay/conflict, cross-tenant denial, and restart recovery. Supply the configured service endpoints and secrets through the authorized environment. See `.env.example` and the runner's argument help. Mock-model checks are local contract evidence and do not establish a live model or database run.
