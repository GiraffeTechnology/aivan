# AIVAN — Private-Domain AI Trade Execution Worker

`Python 3.11+` | `AIVAN v0.2.0` | `Standalone Product` | `OpenClaw Gateway` | `giraffe-language-skill` | `giraffe-db` | `GLTG` | `Human Approval`

AIVAN is a private-domain AI trade execution worker for high-stakes RFQ and quote workflows.

It receives buyer inquiries from approved communication channels through OpenClaw, canonicalizes multilingual input through `giraffe-language-skill`, structures RFQ intake data, checks private-domain facts through AIVAN DB / giraffe-db, calls GLTG for lead-time feasibility, drafts supplier or buyer messages, and keeps all counterparty-facing actions behind a mandatory human approval gate.

AIVAN is not a generic chatbot. It is an auditable trade-execution system for trading companies, merchandisers, sourcing teams, and cross-border procurement operators.

---

## Current Status

```text
Current product role: standalone private-domain trade execution worker
Current package: AIVAN v0.2.0
Primary runtime: FastAPI + local DB + OpenClaw bridge
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
-> private-domain lookup in AIVAN DB / giraffe-db
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

Current default is v1-compatible lead-time estimation. The active roadmap is to support GLTG v2 behavior/statistical simulation:

```text
POST /v2/lead-time/simulate
POST /v2/paths/enumerate
POST /v2/reforecast
```

AIVAN should support:

```text
GLTG_API_VERSION=v1|v2
v2 request builder
v2 response parser
v1 compatibility wrapper
mock v2 transport tests
source_observation_ids propagation
gltg_run_id persistence
```

AIVAN must not calculate lead time locally and must not silently replace GLTG with LLM guesses.

---

## giraffe-db / Private Data Contract

AIVAN consumes private-domain facts from AIVAN DB and giraffe-db.

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
OPENCLAW_GATEWAY_URL=http://localhost:3000
```

GLTG:

```bash
GLTG_API_BASE_URL=http://localhost:8090
GLTG_API_TIMEOUT_SECONDS=30
# future:
# GLTG_API_VERSION=v1
```

Language boundary:

```bash
GIRAFFE_LANGUAGE_SKILL_BASE_URL=http://localhost:8780
GIRAFFE_INTERNAL_LANGUAGE=en
```

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

---

## License

See `LICENSE`.
