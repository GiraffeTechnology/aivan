# @giraffetechnology/openclaw-aivan

OpenClaw plugin bridge for **Aivan**, Giraffe Agent's frontend for inquiry, quotation and order confirmation.

---

## What is AIVAN?

Aivan is the digital trade assistant frontend of Giraffe Agent. MyAivan is its web version; abcdYi is the apparel/textile industry application whose frontend calls Aivan. OpenClaw-Aivan is the IM/email access dependency, with GLTG/GPM invoked through APIs. The replaceable private-domain DB stores business history and process state.

The plugin transports events and authorized requests; it does not own commercial decisions or create a second system of record. Human review, tenant isolation, accurate delivery state and credential protection remain required. See [the product requirements](../../docs/AIVAN_PRODUCT_PRD.md).

---

## What this plugin does

This plugin is a **thin HTTP bridge** between OpenClaw and your local AIVAN server. It:

- Receives normalised OpenClaw events (buyer messages, supplier replies)
- Forwards them to your local AIVAN server at `POST ${AIVAN_BASE_URL}/invoke`
- Exposes helper commands to check AIVAN health and open the local dashboard
- Lets OpenClaw operators view, approve, or reject pending outbound drafts

The plugin contains **no business logic**. All sourcing, risk-screening, lead-time calculation, and option generation happens inside AIVAN.

---

## How OpenClaw connects to AIVAN

```
OpenClaw platform
       │
       │  normalised event (JSON)
       ▼
@giraffetechnology/openclaw-aivan  (this plugin)
       │
       │  POST /invoke
       ▼
AIVAN local server  (http://127.0.0.1:8765)
       │
       │  persists pending draft
       ▼
Human operator approves in AIVAN dashboard
       │
       │  POST /api/drafts/{id}/approve
       ▼
Authorized channel action / manual IM relay
```

---

## Install

For the unpublished explicit-routing compatibility candidate, review
[existing Gateway reuse](EXISTING_GATEWAY_REUSE.md) before changing a working
WeChat installation. The candidate does not install or upgrade Tencent's channel
plugin, log in an account, or enable automatic replies.

### 1. Install and run AIVAN locally

```bash
git clone https://github.com/GiraffeTechnology/aivan.git
cd aivan
cp .env.example .env
uv sync
uv run aivan init
uv run aivan serve
# → http://127.0.0.1:8765/app
```

### 2. Install this plugin in your OpenClaw workspace

```bash
clawhub package install @giraffetechnology/openclaw-aivan
```

Or during development, from this directory:

```bash
npm install
npm run build
clawhub package link .
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AIVAN_BASE_URL` | Yes | `http://127.0.0.1:8765` | URL of the local AIVAN server |
| `AIVAN_API_KEY` | No | *(none)* | Optional API key sent as `X-AIVAN-API-Key` header; set in AIVAN `.env` to enable auth |
| `AIVAN_CONNECT_TIMEOUT_MS` | No | `3000` | Explicit connection timeout in milliseconds |
| `AIVAN_READ_TIMEOUT_MS` | No | `15000` | Explicit response-read timeout in milliseconds |
| `AIVAN_MAX_RETRIES` | No | `1` | Bounded retries (0-2) for idempotent calls only |
| `AIVAN_TENANT_ID` | Production | *(none)* | Static trusted tenant identity for this plugin process |
| `AIVAN_ACTOR_ID` | Production | *(none)* | Static trusted service actor for this plugin process |
| `AIVAN_ROLE_CONTEXT` | Production | *(none)* | Static Core role context for the service actor |
| `AIVAN_CONVERSATION_ROLE` | No | *(none)* | Static conversation role for the service actor |
| `AIVAN_EXECUTION_MODE` | No | *(none)* | Static execution mode for the service actor |
| `AIVAN_CHANNEL_ACCOUNT_ID` | Production channel binding | *(none)* | Trusted channel account for this plugin process |

`aivan.forwardEvent` supplies a stable `Idempotency-Key`, so connection, 429 and
5xx failures can be retried without duplicating an inbound event. Approval and
rejection actions are never automatically retried. Failures are returned as
user-visible `AIVAN_*` error codes with a `retryable` flag.

Set these in your OpenClaw workspace or in the shell before starting the OpenClaw agent.

### Service and participant identity

The process environment supplies the static service identity. The current bridge
separately derives a participant ID from the event channel, account (or `default`)
and sender, and sends participant role/conversation headers. Internal/operator
role aliases are reduced to buyer for participant attribution; they do not grant
operator capabilities. Aivan Core still authenticates the service, binds the
tenant/account and enforces role and object access.

This supersedes the historical Stage 3 statement that every message has only one
service identity. It does not establish a live provider's sender authenticity.
The upstream gateway must supply trustworthy sender, account and role metadata;
missing SDK metadata and fallback identities require integration validation.
The checked-in gateway harness uses synthetic inputs, not real IM accounts.

The legacy `content/from_user/room_id` callback is a supported input shape, not
proof of a personal WeChat or WeCom connection. No WeCom-specific login, signature
verification or account connector is implemented in this bridge. Account access
belongs to the configured OpenClaw gateway; do not bypass platform restrictions.

---

## Mock mode

AIVAN ships with a complete mock mode that requires no live credentials:

```bash
# .env
AIVAN_LLM_PROVIDER=mock
OPENCLAW_MOCK_MODE=true
```

In mock mode:
- All LLM calls return deterministic mock responses
- OpenClaw events are simulated without a real IM/email connection
- No external API calls are made
- Test results must be recorded for the exact candidate; mock success does not establish live channel delivery

---

## Human approval gate

**Every outbound message drafted by AIVAN requires explicit human approval before it is sent.**

Inbound trade messages handled by the Agent Harness are intentionally silent on
personal IM channels: the harness records the AIVAN result but returns no
`assistantTexts`. It also marks the attempt as handled so OpenClaw cannot fall
through to an automatic model reply. The operator must review a pending draft
and use the approved send or guided-relay flow for every outbound message.

The workflow:
1. Match the inbound event against `intent-boundary.json`.
2. For a match, invoke `$aivan-trade-salesperson` before generic assistant or
   fallback skills, as required by `workflow.json`.
3. AIVAN processes the event and creates a pending draft.
4. `aivan.getPendingDrafts` returns the draft to the operator.
5. The operator reviews the message in the AIVAN dashboard or via
   `aivan.approveDraft`.
6. Execute only the authorized action supported by the selected channel policy. In the first MyAivan web iteration all IM channels use manual copy/send/confirmation; configured email uses explicit confirmation, with an honest copy fallback when unavailable.

OpenClaw has no generic numeric priority field for skills. The explicit
`$aivan-trade-salesperson` reference is the supported workflow-level skill
invocation, and the skill description carries the same first-match rule in the
eligible-skill catalog. The Agent Harness `supports()` phase receives
provider/model facts rather than the inbound prompt, so it is not used to fake
message-level skill priority. Once explicitly selected, a non-trade attempt
returns no reply and makes no Core call; this does not replay the turn through
another runtime. The workflow boundary metadata is not an SDK handoff. Neither
mechanism authorizes outbound delivery.

The plugin cannot bypass this gate. Calling `aivan.approveDraft` sends the action to the AIVAN API, which enforces the policy server-side.

---

## Data and language boundary

The private-domain DB is the replaceable system of record for business history and process state; chat/LLM context and local caches are not business truth. The two designated simulated DBs are valid acceptance sources when the actual application and API path execute. Fake transport responses remain mock-test evidence.

Standard English is the work/interaction language. Non-English input/output uses dynamic `giraffe-language-skill` translation. Except enterprise/user profiles, the DB must not store non-English content. The account/connectivity layer owns credentials. Local-first does not mean that configured remote services receive no data; approved dependency processing and external business sending have distinct permissions.

---

## How to test

Run AIVAN in mock mode and execute the validation scripts:

```bash
# Terminal 1
uv run aivan serve

# Terminal 2
python scripts/validate_clawhub_aivan_plugin.py
python scripts/run_aivan_openclaw_plugin_smoke_test.py
```

Run the Python test suite:

```bash
uv run pytest
```

---

## How to dry-run ClawHub publication

```bash
npm install -g clawhub
clawhub login
clawhub whoami
clawhub package publish integrations/openclaw-aivan-plugin --family code-plugin --dry-run
```

This validates metadata and package structure without actually publishing.

---

## Available commands

| Command | Type | Description |
|---|---|---|
| `aivan.health` | command | Ping the local AIVAN server |
| `aivan.forwardEvent` | event-handler | Forward an OpenClaw event to AIVAN |
| `aivan.openDashboard` | command | Return the local dashboard URL |
| `aivan.getPendingDrafts` | query | List drafts awaiting approval |
| `aivan.approveDraft` | action | Approve a pending draft for sending |
| `aivan.rejectDraft` | action | Reject and discard a pending draft |

