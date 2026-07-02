# @giraffetechnology/openclaw-aivan

OpenClaw plugin bridge for **AIVAN** — a local-first AI trade salesperson assistant.

---

## What is AIVAN?

AIVAN is a standalone, local-first AI assistant that helps trading-company salespeople manage the full sourcing cycle:

- Receive buyer inquiries → structure requirements
- Find and screen suppliers (registry + marketplace search)
- Draft outbound messages (inquiries, options, confirmations)
- Screen supplier risk
- Calculate lead-time estimates (P50/P80/P90)
- Generate buyer option comparisons
- Manage order execution milestones

AIVAN runs entirely on your machine. No buyer data, supplier data, or conversation history leaves your network unless you explicitly approve a message to be sent via OpenClaw.

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
AIVAN sends via OpenClaw SDK
```

---

## Install

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

Set these in your OpenClaw workspace or in the shell before starting the OpenClaw agent.

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
- All tests pass

---

## Human approval gate

**Every outbound message drafted by AIVAN requires explicit human approval before it is sent.**

The workflow:
1. AIVAN processes an event and creates a pending draft
2. `aivan.getPendingDrafts` returns the draft to the operator
3. The operator reviews the message in the AIVAN dashboard or via `aivan.approveDraft`
4. Only after approval does AIVAN send the message via OpenClaw

The plugin cannot bypass this gate. Calling `aivan.approveDraft` sends the action to the AIVAN API, which enforces the policy server-side.

---

## Local-first data boundary

All data — buyer requirements, supplier details, conversations, drafts, risk reports, lead-time estimates — is stored in a local SQLite database (`data/aivan.db`). Nothing is synced to Giraffe Technology servers or any third-party cloud service unless you explicitly configure an external LLM provider.

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
