# AIVAN — Trade Monitoring and Human-Takeover Control Plane

`Python 3.11+` | `AIVAN v0.3.0` | `Control Plane` | `OpenClaw Gateway` | `giraffe-language-skill` | `giraffe-db` | `GLTG` | `Human Approval`

AIVAN is the monitoring and human-takeover control plane for high-stakes RFQ and quote workflows.

It receives buyer inquiries from approved communication channels through OpenClaw, canonicalizes multilingual input through `giraffe-language-skill`, consumes non-QC business facts through versioned `giraffe-db` contracts, calls GLTG for lead-time feasibility, prepares controlled drafts, and keeps all counterparty-facing actions behind a mandatory human approval gate.

AIVAN is not a generic chatbot or a second business system of record. Its durable local scope is limited to control state, audit evidence, and explicitly versioned short-lived cache/projection data. Existing local business tables are legacy implementation debt and must not be treated as authoritative in production; their consumer cutover is Stage D work.

---

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/GiraffeTechnology/aivan.git
cd aivan
./scripts/bootstrap_local.sh   # copies .env.example -> .env, uv sync, aivan init
```

Or manually:

```bash
cp .env.example .env
uv sync
uv run aivan init
```

## Run locally

```bash
uv run aivan serve             # FastAPI server on AIVAN_HOST:AIVAN_PORT (default 127.0.0.1:8765)
uv run aivan demo              # offline core RFQ demo (mock providers)
```

The local dashboard is served at `http://127.0.0.1:8765/app`.

## Test

```bash
uv run pytest -q                                              # unit + contract tests, offline
uv run python scripts/validate_clawhub_aivan_plugin.py        # ClawHub plugin metadata
uv run python scripts/run_aivan_openclaw_plugin_smoke_test.py --offline
uv run python scripts/run_aivan_openclaw_full_check.py        # full OpenClaw plugin check
uv run python scripts/run_private_domain_rfq_e2e.py           # offline private-domain RFQ loop
uv run python scripts/run_aivan_e2e.py                        # full E2E (requires a live GLTG server)
```

---

## OpenClaw Gateway Discovery and Install

OpenClaw connects to AIVAN through the bridge plugin in
`integrations/openclaw-aivan-plugin/`:

- **Discovery.** The plugin manifest `openclaw.plugin.json` declares the stable
  plugin id `openclaw-aivan`, `activation.onStartup`, and an `aivanBaseUrl`
  config schema. The npm package `@giraffetechnology/openclaw-aivan` points
  `main`/`exports` and `openclaw.extensions` at the committed `dist/index.js`.
- **Registration.** The built entry default-exports a `definePluginEntry`
  object; OpenClaw calls its `register(api)`, which registers an agent harness
  (id `openclaw-aivan`) via `api.registerAgentHarness(...)`.
- **Invocation.** The harness's `runAttempt` normalizes the inbound IM/email
  message into an OpenClaw-standard event and POSTs it to the local AIVAN
  server (`AIVAN_BASE_URL`, default `http://127.0.0.1:8765`) at `/invoke`.
  AIVAN also exposes `/api/openclaw/events`, `/api/skill/invoke`, and
  `/api/rfq/create-from-event` for the same event contract.
- **Skill listing.** `skills/aivan-trade-salesperson/SKILL.md` is the ClawHub
  skill listing (slug `aivan-trade-salesperson`); it routes trade-sourcing
  intent to the plugin and holds no business logic.

These contracts are enforced by `tests/test_gateway_metadata_contract.py` and
the `scripts/run_aivan_openclaw_*` check scripts.

## B/M Role Switching

Every OpenClaw event carries a `role_context`. AIVAN routes on it:

- `buyer`, `customer`, `b_side` (or empty) → treated as a buyer-side (B) inquiry:
  requirement structuring, supplier routing, quote drafting.
- `supplier`, `seller`, `m_side` → treated as a supplier-side (M) reply:
  parsed into a structured supplier quote and attached to the owning project.
- `user` with `mode=command` → operator commands to AIVAN itself.

Supplier-side events are never misclassified as new buyer inquiries;
`project_id` and `role_context` are preserved end-to-end through the plugin
(verified by `scripts/run_aivan_openclaw_gateway_p0_test.py`).

## Buyer → Supplier → Buyer Loop

1. **Buyer inquiry** arrives as an OpenClaw event and is structured into a
   provenance-tagged requirement (language skill first for non-English input).
2. **Intermediary handling**: AIVAN looks up private-domain context
   (suppliers, history) and drafts supplier inquiry emails/IMs — all pending
   human approval.
3. **Supplier replies** are parsed (`parse_supplier_reply`) into unit price,
   MOQ, lead time, and terms; missing fields stay `None` and never crash the flow.
4. **Markup**: `calculate_buyer_quote` applies the configured margin
   (`AIVAN_DEFAULT_MARGIN_RATE` or a fixed margin) on top of supplier cost.
5. **Freight / insurance**: domestic and international logistics fees are
   added as pass-through costs before margin.
6. **Lead time**: GLTG P50/P80/P90 estimates set `risk_buffer_days`
   (conservative vs expected delivery) and deadline feasibility.
7. **Final buyer reply**: Top-3 options (fastest / lowest cost / most
   reliable) with supplier identity and cost hidden when configured — again
   behind the human approval gate.

---

## Current Status

```text
Current product role: monitoring and human-takeover control plane
Current package: AIVAN v0.3.0
Primary runtime: FastAPI control plane + OpenClaw bridge
Primary channel path: OpenClaw normalized events
GLTG integration: v1 HTTP client, v2 contract target
Language boundary: giraffe-language-skill P0 required for non-English input
Human approval: mandatory for outbound counterparty actions
```

Validated / implemented areas:

```text
local install and CLI flows
FastAPI health and event endpoints
OpenClaw plugin bridge structure
WeChat-priority live channel path through OpenClaw
RFQ / project / draft workflow skeleton
Giraffe DB / GPM context contract
GLTG v1 lead-time call path
human approval draft workflow
```

Known active gaps:

```text
production GLTG v2 behavior/statistical simulation is not yet the default
non-English raw RFQ extraction must be blocked until language-skill integration is complete
live model/provider availability depends on configured backend services
ClawHub/public production packaging requires final release gate validation
```

---

## System Boundary

AIVAN owns trade execution workflow logic. It does not own every infrastructure layer.

```text
OpenClaw                = channel/account connectivity
giraffe-language-skill  = multilingual canonicalization and output localization
giraffe-db              = private business facts and synthetic/private test data
GLTG                    = lead-time feasibility simulation
GPM                     = procurement graph/path reasoning
AIVAN                   = controlled RFQ execution workflow
Human operator          = legal/commercial approval
```

AIVAN must not silently absorb OpenClaw credentials, language canonicalization rules, private data ownership, GLTG math, or QC model inference.

---

## Controlled Real-Test Email

Real email sending is disabled by default. For an approved OpenClaw real-test run,
set `AIVAN_EMAIL_SEND_MODE=real_test` and `AIVAN_EMAIL_GATEWAY=openclaw_real_test`.
The real-test transport only sends approved drafts, requires
`AIVAN_EMAIL_ALLOWED_RECIPIENTS`, and preserves the human approval gate.

The CTYUN 163 mailbox configuration uses `giraffetechnology@163.com` with SMTP
SSL on `smtp.163.com:465` and POP3 SSL on `pop.163.com:995`. 163 requires a
client authorization code for `AIVAN_SMTP_PASSWORD` / `AIVAN_POP3_PASSWORD`; the
web login password is not accepted for POP3/SMTP client access.

```bash
AIVAN_EMAIL_SEND_MODE=real_test
AIVAN_EMAIL_GATEWAY=openclaw_real_test
AIVAN_EMAIL_ALLOWED_RECIPIENTS=mich@giraffe.technology
AIVAN_PRESET_MAILBOX=giraffetechnology@163.com
AIVAN_SMTP_HOST=smtp.163.com
AIVAN_SMTP_PORT=465
AIVAN_SMTP_USE_SSL=true
AIVAN_SMTP_USE_TLS=false
AIVAN_SMTP_USERNAME=giraffetechnology@163.com
AIVAN_SMTP_PASSWORD=<163-client-authorization-code>
AIVAN_POP3_HOST=pop.163.com
AIVAN_POP3_PORT=995
AIVAN_POP3_USE_SSL=true
AIVAN_POP3_USERNAME=giraffetechnology@163.com
AIVAN_POP3_PASSWORD=<163-client-authorization-code>
```

---

## P0 Language Boundary

Standard English is the only internal working language across Giraffe products.

For non-English buyer, supplier, operator, IM, email, marketplace, or RFQ input:

```text
raw multilingual input
-> giraffe-language-skill
-> canonical English packet
-> AIVAN RFQ/workflow logic
-> giraffe-db / GPM / GLTG calls
-> decision packet / draft
-> localized user-facing output
```

AIVAN must not:

```text
call its requirement LLM with raw non-English business text
run deterministic fallback extraction over raw non-English business text
infer product/category/destination/material/quality/supplier capability/price/lead time from raw non-English text
write graph data from raw non-English input
call GLTG from raw non-English input
create outbound drafts from raw non-English input
```

If `giraffe-language-skill` is unavailable or cannot produce a valid canonical packet, AIVAN must block local extraction and ask for canonicalization or operator confirmation.

English RFQs may continue through AIVAN's existing local LLM and deterministic fallback path, with language-skill normalization used when available.

---

## Core Workflow

```text
Buyer inquiry / operator command
-> OpenClaw normalized event
-> language boundary check
-> giraffe-language-skill canonical packet if needed
-> RFQ/project workspace detection
-> requirement structuring
-> versioned private-domain lookup through giraffe-db
-> supplier routing / GPM context
-> GLTG lead-time feasibility
-> quote / supplier-follow-up draft
-> operator approval request
-> approved outbound execution
-> execution graph / memory update
-> localized user-facing summary
```

---

## GLTG Integration

Current AIVAN GLTG integration targets the standalone GLTG service:

```bash
GLTG_API_BASE_URL=http://localhost:8090
GLTG_API_TIMEOUT_SECONDS=30
```

Current default is v1-compatible lead-time estimation. Setting
`GLTG_API_VERSION=v2` switches the client to the v2 simulation endpoints:

```text
POST /v2/lead-time/simulate
POST /v2/paths/enumerate
POST /v2/reforecast
```

The v2 behavior/statistical simulation rollout (full request builder,
`source_observation_ids` propagation, `gltg_run_id` persistence) is tracked in
`docs/GLTG_BEHAVIORAL_STATISTICAL_MODEL_ITERATION_PRD.md`.

AIVAN must not calculate lead time locally and must not silently replace GLTG with LLM guesses.

---

## giraffe-db / Private Data Contract

AIVAN consumes all non-QC private-domain business facts through versioned giraffe-db APIs/SDKs. Local storage may contain only control state, audit evidence, or a declared cache/projection carrying source version, TTL, invalidation, and rebuild semantics.

Expected data categories include:

```text
customers / buyers
suppliers
supplier products
historical RFQs
historical quotes
leadtime observations
supplier capacity snapshots
risk events
behavior observations
buyer behavior snapshots
supplier behavior snapshots
buyer-supplier pair metrics
gltg simulation runs
gltg behavior inputs
execution events
audit records
```

Synthetic records from `synthetic_private_v1` must remain clearly labeled as synthetic and must not be represented as real transaction history.

---

## Human Approval Boundary

AIVAN can draft and recommend. It cannot legally or commercially commit by itself.

Human approval is required for:

```text
supplier inquiries
buyer quotations
supplier selection
delivery commitment
order confirmation
payment instruction
contractual commitment
high-risk exception handling
```

---

## Environment

Core runtime:

```bash
AIVAN_ENV=local
AIVAN_HOST=127.0.0.1
AIVAN_PORT=8765
AIVAN_DB_URL=sqlite:///./data/aivan.db
AIVAN_REQUIRE_HUMAN_APPROVAL=true
```

OpenClaw:

```bash
OPENCLAW_BASE_URL=http://localhost:3000
OPENCLAW_MOCK_MODE=true
```

GLTG:

```bash
GLTG_API_BASE_URL=http://localhost:8090
GLTG_API_TIMEOUT_SECONDS=30
GLTG_API_VERSION=v1
```

Language boundary:

```bash
AIVAN_LANGUAGE_SKILL_ENABLED=true
AIVAN_LANGUAGE_SKILL_BASE_URL=http://127.0.0.1:8788
AIVAN_LANGUAGE_SKILL_FAIL_SOFT=true
```

See `.env.example` for the full annotated list.

Production is intentionally stricter:

- set `AIVAN_DB_URL` explicitly through the authorized configuration store;
- bind `AIVAN_API_KEY` to `AIVAN_TENANT_ID`, or use a reviewed
  `AIVAN_TENANT_API_KEYS` mapping;
- set `GIRAFFE_DB_BASE_URL` for GPM durable persistence and active-tenant checks;
- set `AIVAN_CORS_ORIGINS` to an exact comma-separated browser allowlist
  (production defaults to none and rejects `*`);
- treat `deploy/aivan.production.env.example` as a schema, not as authorization
  to deploy or modify a host.

In production, a caller-supplied `X-Tenant-ID` is never authentication. GPM
fails closed when giraffe-db is missing, unavailable, or not durable.

LLM providers are optional and must not bypass deterministic gates, GLTG, giraffe-db, or the language boundary.

---

## Required Tests

AIVAN must test:

```text
non-English input calls giraffe-language-skill first
non-English input without valid canonical packet is blocked
local LLM never receives raw non-English business text
deterministic fallback does not canonicalize raw non-English fields
GLTG v1 path still works
GLTG v2 mock transport works when enabled
GLTG failure surfaces error instead of silent local fallback
human approval is required before outbound messages
localized output is separate from canonical English internal state
static guards reject multilingual alias maps inside AIVAN
```

---

## Product Principle

```text
Language is normalized by giraffe-language-skill.
Facts come from giraffe-db.
Lead time comes from GLTG.
Procurement path reasoning comes from GPM.
Channel connectivity comes from OpenClaw.
Execution control lives in AIVAN.
Final responsibility stays with humans.
```

### Stage 4 channel delivery contract

| Channel | Delivery mode |
| --- | --- |
| Email | `auto_send` |
| LINE | `auto_send` |
| WeChat / Wangwang | `guided_relay` |
| WhatsApp | `unsupported` |

Guided relay keeps approved messages in `GET /api/relay/outbox`. After a human
copies and sends the message in the channel client, the client records delivery
through `POST /api/relay/{draft_id}/confirm` with an `Idempotency-Key` and a
receipt reference. Relayed replies enter the same tenant-scoped Case pipeline
through `POST /api/relay/inbound`; they are not attributed to a fixed service
actor.

---

## License

See `LICENSE`.
