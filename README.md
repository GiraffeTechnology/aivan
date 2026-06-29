# AIVAN — AI Trade Salesperson

`Python 3.11+` | `Standalone Product` | `OpenClaw Gateway` | `Multi-LLM` | `Giraffe DB` | `GLTG` | `Human-in-the-loop`

AIVAN is a standalone AI trade salesperson assistant extracted from the broader Giraffe Agent architecture. It receives buyer inquiries, structures RFQs, looks up private-domain supplier/customer context, screens risks, calls GLTG for lead-time simulation, drafts counterparty messages, and keeps a human approval gate before anything is sent.

AIVAN is not a generic chatbot. It is an auditable trade execution system for private-domain RFQ workflows.

---

## Current Status — Live WeChat Connectivity PASS, Backend Dependency BLOCKED

Latest live WeChat verification: **2026-06-30**.

AIVAN has now passed the live WeChat connectivity milestone. A real WeChat message sent to `WeixinClawBot` triggered an AIVAN/OpenClaw-side response instead of being dropped before the agent layer.

The current blocker has moved from **WeChat connectivity** to **AIVAN backend dependency availability**. The live verification response showed:

```text
Model Fallback: aivan/aivan
(selected ollama/qwen3.5:0.8b; selected model unavailable)

AIVAN 处理请求时遇到后端依赖错误，请稍后再试。
```

This means the WeChat invocation path is alive, but the selected local model / backend dependency was unavailable, so AIVAN could not complete the RFQ business workflow.

### Validated environment

```text
AIVAN runtime: v0.2.0
AIVAN runtime port: 8000 in server deployment
Database: PostgreSQL in server deployment; SQLite for local development
OpenClaw Gateway: v2026.6.10 test target
OpenClaw plugin: openclaw-aivan
Plugin package: @giraffetechnology/openclaw-aivan v0.1.0
Live IM bridge: WeixinClawBot
Selected local model under test: ollama/qwen3.5:0.8b
```

### Acceptance matrix

| Area | Status | Notes |
|---|---:|---|
| Local mock-mode install | PASS | No live credentials required. |
| Local AIVAN E2E demos | PASS | RFQ, marketplace, risk, whitelist, and approval-gate flows run in mock mode. |
| AIVAN server runtime | PASS | Server can run independently. |
| PostgreSQL deployment | PASS | Server-side DB connection validated. |
| OpenClaw Gateway process | PASS | Gateway can run in the server environment. |
| `openclaw-aivan` package build/typecheck | PASS | TypeScript build and metadata are aligned with OpenClaw plugin requirements. |
| `openclaw-aivan` plugin install/load/inspect | PASS | Plugin can be discovered, installed, loaded, and inspected by Gateway in the tested environment. |
| Gateway/plugin to AIVAN event endpoint | PASS | Server-side event forwarding path is available. |
| WeixinClawBot live response | PASS | A real WeChat message produced a bot response. |
| Live WeChat → OpenClaw/AIVAN invocation | PASS | AIVAN/OpenClaw returned a model fallback/backend dependency message, proving the request reached the agent-side invocation path. |
| Selected local model availability | **FAIL / P0 BLOCKER** | `ollama/qwen3.5:0.8b` was selected but unavailable during live verification. |
| Live AIVAN RFQ business completion | **BLOCKED** | RFQ/project creation and pending approval draft still require backend dependency availability. |
| ClawHub production publication | NOT READY | Requires live business-flow acceptance, not only connectivity. |

### Current P0 blocker

The WeChat channel is no longer the primary blocker. The next fix must focus on backend dependency readiness:

```text
WeChat user command
→ WeixinClawBot
→ OpenClaw Gateway / AIVAN invocation
→ selected AIVAN model/provider
→ AIVAN POST /api/openclaw/events
→ RFQ/project creation
→ pending draft / approval request
```

Current observed failure point:

```text
selected ollama/qwen3.5:0.8b unavailable
backend dependency error
```

Required next acceptance target:

```text
A real WeChat command reaches AIVAN.
The configured local model/provider is available.
AIVAN creates or updates an RFQ/project.
AIVAN stores the inbound event and OpenClaw context.
AIVAN generates a pending draft or structured approval request.
AIVAN does not send any counterparty message without human approval.
```

Example live acceptance message:

```text
帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华
```

Expected final business result:

```text
AIVAN creates or updates an RFQ/project.
AIVAN stores the inbound event and OpenClaw context.
AIVAN generates a pending draft or structured approval request.
No outbound counterparty message is sent without human approval.
```

---

## Product Positioning

Trading company salespeople handle repetitive, time-sensitive tasks: parsing buyer inquiries, finding suitable suppliers, chasing quotations, comparing options, calculating feasibility, and drafting buyer/supplier responses. AIVAN automates the structured work while keeping the salesperson in control of every counterparty-facing action.

AIVAN is developed first as a standalone product. Once stable, its capabilities can be forked, ported, or integrated into `abcdYi` and the broader `giraffe-agent` framework. Runtime, OpenClaw Gateway, private-domain RFQ, GLTG, and approval-gate fixes belong here first.

---

## Product Boundary

AIVAN owns:

```text
RFQ/project workflow
Trade event classification
Private-domain context orchestration
Giraffe DB access
GLTG lead-time simulation calls
Supplier-routing decisions
User preference memory usage
Email draft creation
Human approval workflow
Audit trails
Channel execution policy
OpenClaw event ingestion
```

AIVAN does **not** own:

```text
IM account login
WeChat/LINE/WhatsApp credential storage
CAPTCHA bypass
Platform anti-bot bypass
Unapproved outbound communication
Final legal, credit, sanctions, or compliance decisions
```

OpenClaw owns account connectivity. AIVAN owns trade execution logic.

---

## Key Product Rules

1. Human approval is required for all counterparty outbound messages.
2. AIVAN never stores platform passwords, cookies, session tokens, or credential material.
3. AIVAN never bypasses login, CAPTCHA, anti-bot systems, access controls, rate limits, or platform rules.
4. A trusted platform does not mean every supplier on that platform is trusted.
5. Supplier-level risk screening is independent from platform-level trust.
6. AIVAN does not make final legal, credit, sanctions, or trade compliance decisions.
7. AIVAN must not hallucinate supplier facts, customer history, price history, lead-time history, or user preference memory.
8. Giraffe DB is the private-domain business fact source.
9. GLTG is the lead-time simulation source.
10. LLMs provide controlled strategy intelligence, not business facts.
11. WeChat, LINE, WhatsApp, and similar IM channels are user-control channels.
12. Current counterparty outbound execution is email-first unless an official, API-permitted, auditable channel is implemented and approved.
13. Never log API keys, credentials, cookies, tokens, or private server secrets.

---

## Architecture Overview

```text
User IM / Email / Marketplace Account
                │
                ▼
        OpenClaw Gateway
                │
                ▼
       openclaw-aivan plugin
                │
                ▼
     AIVAN /api/openclaw/events
                │
                ├── Requirement Agent
                ├── Supplier Inquiry Agent
                ├── Risk Screener
                ├── Buyer Option Agent
                ├── Giraffe DB private-domain lookup
                ├── GLTG lead-time simulation client
                └── LLM strategy interpretation
                │
                ▼
        Human Approval Gate
                │
                ▼
  Approved outbound execution through OpenClaw/email integration
```

Storage:

```text
Local development: SQLite
Server deployment: PostgreSQL
Stored state: projects, events, drafts, suppliers, accounts, platforms, preferences, approvals, risk flags
```

LLM providers:

```text
mock | OpenAI | Anthropic/Claude | Google/Gemini | DeepSeek | Qwen | Ollama
```

---

## Private-Domain Data and Giraffe DB

Giraffe DB is AIVAN's private-domain source of truth. AIVAN queries it for customers, customer preferences, suppliers, supplier relationships, historical RFQs, historical quotations, historical lead-time records, product categories, user preferences, approval history, draft revision history, and risk flags.

AIVAN must never ask an LLM to infer private supplier facts, customer history, historical prices, historical lead times, or user preference memory from general knowledge. The LLM may reason over Giraffe DB context supplied by AIVAN, but Giraffe DB remains the business fact source.

---

## GLTG Lead-Time Simulation

GLTG is a standalone external service:

```text
https://github.com/GiraffeTechnology/GLTG
```

AIVAN calls GLTG over HTTP through:

```text
src/aivan/integrations/gltg_client.py
```

Configure the GLTG client with:

```env
GLTG_API_BASE_URL=http://localhost:8090
GLTG_API_TIMEOUT_SECONDS=30
```

The client returns a structured `GLTGClientResult(ok, data, error, status_code)` and must not fall back to local lead-time invention. The LLM may explain GLTG outputs, but it must not replace GLTG calculations.

---

## LLM Strategy Intelligence

LLMs are used for:

```text
intent understanding
user preference interpretation
strategy translation
contextual reasoning over AIVAN-provided DB/GLTG context
email summarization
customer/supplier message classification
draft generation
reason explanation
post-action review
preference extraction
```

Workflow-affecting outputs must be structured, validated, and guarded by deterministic fallbacks. The approval gate remains mandatory regardless of LLM output.

---

## Install

```bash
git clone https://github.com/GiraffeTechnology/aivan.git
cd aivan
cp .env.example .env
uv sync
uv run aivan init
```

No live credentials are required to install or run in mock mode.

---

## Quick Start

```bash
uv run aivan demo                    # Core E2E demo, mock mode
uv run aivan demo-marketplace        # Marketplace search demo
uv run aivan demo-risk-check         # Risk screening demo
uv run aivan serve                   # Start web UI
```

Open the web UI after starting the server:

```text
http://127.0.0.1:8765/app
```

For server deployment, set `AIVAN_HOST`, `AIVAN_PORT`, and `AIVAN_DB_URL` explicitly.

---

## Environment Variables

All variables are set in `.env`. Copy `.env.example` to get started.

### Core

| Variable | Default | Description |
|---|---|---|
| `AIVAN_ENV` | `local` | Runtime environment: `local` or `production`. |
| `AIVAN_HOST` | `127.0.0.1` | Host address for the web server. |
| `AIVAN_PORT` | `8765` | Web server port. Server deployments may use `8000`. |
| `AIVAN_DB_URL` | `sqlite:///./data/aivan.db` | Database URL. SQLite locally; PostgreSQL in server deployment. |
| `AIVAN_LOG_LEVEL` | `INFO` | Logging level. |
| `AIVAN_REQUIRE_HUMAN_APPROVAL` | `true` | Enforce approval gate for all outbound messages. |

Example PostgreSQL URL:

```env
AIVAN_DB_URL=postgresql://aivan:<password>@127.0.0.1:5432/aivan
```

### OpenClaw

| Variable | Default | Description |
|---|---|---|
| `OPENCLAW_BASE_URL` | empty | Base URL of the OpenClaw HTTP API. |
| `OPENCLAW_API_KEY` | empty | API key for authenticating with OpenClaw. |
| `OPENCLAW_SEND_ENDPOINT` | `/messages/send` | Endpoint for sending messages through OpenClaw. |
| `OPENCLAW_MOCK_MODE` | `true` | Use mock OpenClaw responses. |
| `OPENCLAW_MARKETPLACE_ENABLED` | `true` | Enable marketplace search/contact through OpenClaw. |
| `OPENCLAW_MARKETPLACE_SEARCH_ENDPOINT` | `/marketplaces/search` | Marketplace search endpoint. |
| `OPENCLAW_MARKETPLACE_CONTACT_ENDPOINT` | `/marketplaces/contact` | Marketplace contact endpoint. |
| `OPENCLAW_SEARCH_ENABLED` | `true` | Allow OpenClaw to fulfill web search requests. |
| `OPENCLAW_SEARCH_ENDPOINT` | `/search/web` | OpenClaw web search endpoint. |

### LLM

| Variable | Default | Description |
|---|---|---|
| `AIVAN_LLM_PROVIDER` | `mock` | `mock`, `openai`, `anthropic`, `google`, `deepseek`, `qwen`, or `ollama`. |
| `OPENAI_API_KEY` | empty | Required when provider is `openai`. |
| `OPENAI_BASE_URL` | empty | Optional custom OpenAI-compatible endpoint. |
| `OPENAI_MODEL` | empty | OpenAI model name. |
| `ANTHROPIC_API_KEY` | empty | Required when provider is `anthropic`. |
| `ANTHROPIC_MODEL` | empty | Claude model name. |
| `GOOGLE_API_KEY` | empty | Required when provider is `google`. |
| `GEMINI_MODEL` | empty | Gemini model name. |
| `DEEPSEEK_API_KEY` | empty | Required when provider is `deepseek`. |
| `DEEPSEEK_BASE_URL` | empty | DeepSeek API base URL. |
| `DEEPSEEK_MODEL` | empty | DeepSeek model name. |
| `QWEN_API_KEY` | empty | Required when provider is `qwen`. |
| `QWEN_BASE_URL` | empty | Qwen / DashScope compatible-mode base URL. |
| `QWEN_MODEL` | empty | Qwen model name. |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama native API base URL. Do not include `/v1`. |
| `OLLAMA_MODEL` | `qwen3.5:0.8b` | Local Ollama model name exactly as shown by `ollama list`. |
| `AIVAN_LLM_TIMEOUT_SECONDS` | `30` | LLM request timeout. |
| `AIVAN_LLM_MAX_RETRIES` | `2` | Maximum LLM retries. |
| `AIVAN_LLM_TEMPERATURE` | `0` | Deterministic default. |

Qwen / DashScope-compatible example:

```env
AIVAN_LLM_PROVIDER=qwen
QWEN_API_KEY=sk-...
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

Local Ollama example:

```env
AIVAN_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:0.8b
```

### Alibaba / 1688

| Variable | Default | Description |
|---|---|---|
| `AIVAN_ALIBABA_MODE` | `mock` | `mock` or `live`. |
| `ALIBABA_API_BASE_URL` | empty | Alibaba API base URL. |
| `ALIBABA_APP_KEY` | empty | Alibaba app key. |
| `ALIBABA_APP_SECRET` | empty | Alibaba app secret. |
| `ALIBABA_ACCESS_TOKEN` | empty | Alibaba OAuth access token. |
| `ALIBABA_PLATFORM` | `1688\|alibaba_com\|auto` | Alibaba platform selector. |

### Risk Settings

| Variable | Default | Description |
|---|---|---|
| `AIVAN_ENABLE_UNKNOWN_SUPPLIER_RISK_SEARCH` | `true` | Run web search risk screening on unknown suppliers. |
| `AIVAN_BLOCK_CRITICAL_RISK_SUPPLIERS` | `false` | Block critical-risk suppliers unless manually overridden. |
| `AIVAN_REQUIRE_RISK_REVIEW_FOR_UNKNOWN_SUPPLIERS` | `true` | Require review before unknown suppliers are used. |

### Trade Settings

| Variable | Default | Description |
|---|---|---|
| `AIVAN_DEFAULT_MARGIN_RATE` | `0.15` | Default trading margin. |
| `AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER` | `true` | Do not reveal supplier identity to buyer. |
| `AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER` | `true` | Do not reveal supplier unit price to buyer. |

---

## Platform Whitelist

AIVAN maintains a trusted platform whitelist. Alibaba (`alibaba.com`, `1688.com`) and AliExpress (`aliexpress.com`) are built-in trusted platforms. A trusted platform only means AIVAN may search/contact suppliers on that platform according to configured rules. It does not mean every supplier on that platform is trusted.

Supplier-level risk screening runs independently for every supplier.

Manage the whitelist:

```bash
uv run aivan platforms
```

Platform suggestions pending approval are available at:

```text
GET /api/platforms/suggestions
```

---

## OpenClaw Integration

OpenClaw is the connectivity layer for IM, email, marketplace, and web-search channels. AIVAN communicates with OpenClaw through the native OpenClaw Gateway plugin and the AIVAN event API.

### What OpenClaw manages

```text
Account login and session management
Inbound message delivery
Outbound channel execution after approval
Marketplace search/contact channel access
Web search channel access when configured
```

### What AIVAN stores

AIVAN stores account metadata only:

```text
account ID
platform
display name
status
project/event/draft linkage
```

AIVAN never stores passwords, cookies, session tokens, or credential material.

In mock mode (`OPENCLAW_MOCK_MODE=true`), all OpenClaw interactions are simulated locally.

View connected accounts:

```bash
curl http://127.0.0.1:8765/api/openclaw/accounts
```

---

## Native OpenClaw Gateway Plugin

Plugin path:

```text
integrations/openclaw-aivan-plugin/
```

Plugin metadata:

| Field | Value |
|---|---|
| Package name | `@giraffetechnology/openclaw-aivan` |
| Package version | `0.1.0` |
| Plugin ID | `openclaw-aivan` |
| Runtime entry | `./dist/index.js` |
| Types entry | `./dist/index.d.ts` |
| Manifest | `openclaw.plugin.json` |
| OpenClaw compatibility target | `>=2026.3.22` |
| Tested OpenClaw version | `2026.6.10` |

The plugin registers an OpenClaw AgentHarness via `registerAgentHarness`, extracts the inbound prompt from OpenClaw runtime params, and forwards normalized events to:

```text
POST /api/openclaw/events
```

AIVAN preserves OpenClaw context fields such as:

```text
project_id
role_context
conversation_id
sender_id
channel
```

This context preservation is required for supplier-side replies to be attached to the correct trade project instead of being misclassified as new buyer inquiries.

---

## Build and Install the Plugin Locally

From the plugin directory:

```bash
cd integrations/openclaw-aivan-plugin
npm install
npm run build
npm run typecheck
npx tsc
```

Install through OpenClaw:

```bash
openclaw plugins install . --force
```

Or install from an absolute path:

```bash
openclaw plugins install /opt/giraffe/aivan/integrations/openclaw-aivan-plugin --force
```

Verify installation:

```bash
openclaw plugins list --verbose
openclaw plugins inspect openclaw-aivan --runtime --json
```

Expected plugin-level result:

```text
AIVAN OpenClaw Bridge (openclaw-aivan) enabled
status: loaded
activated: true
diagnostics: []
```

This verifies plugin loading only. Final production readiness also requires live business-flow acceptance.

---

## Running Tests

Run the Python test suite:

```bash
uv run pytest
```

All normal tests run in mock mode. No live credentials, external API calls, or live OpenClaw connection are required.

### OpenClaw Gateway plugin tests

Run these before publishing or modifying the OpenClaw Gateway plugin:

```bash
python scripts/validate_clawhub_aivan_plugin.py
python scripts/run_aivan_openclaw_plugin_smoke_test.py --offline
python scripts/run_aivan_openclaw_install_smoke_test.py
python scripts/run_aivan_openclaw_gateway_p0_test.py
python scripts/run_aivan_openclaw_install_simulation.py
```

From the plugin directory:

```bash
cd integrations/openclaw-aivan-plugin
npm install
npm run build
npm run typecheck
npx tsc
node test-gateway-harness.mjs
```

These tests verify package metadata, local install lifecycle, Gateway inspection, ID alignment, AgentHarness shape, and mock event routing.

### Required live acceptance test

Before claiming production readiness, run a real WeChat command and verify that it reaches AIVAN business logic:

```text
帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华
```

Required result:

```text
OpenClaw receives the WeChat event.
openclaw-aivan receives the OpenClaw runtime call.
AIVAN receives POST /api/openclaw/events.
AIVAN's configured model/provider is available.
AIVAN creates or updates an RFQ/project.
AIVAN records event context.
AIVAN creates a pending draft or approval request.
No unapproved counterparty outbound message is sent.
```

Live WeChat connectivity has passed; business-flow acceptance remains blocked until the backend model/provider dependency is available and the RFQ workflow completes.

---

## Running E2E Scripts

```bash
uv run python scripts/run_aivan_e2e.py
uv run python scripts/run_aivan_private_domain_rfq_e2e.py
uv run python scripts/run_aivan_marketplace_e2e.py
uv run python scripts/run_aivan_unknown_supplier_risk_e2e.py
uv run python scripts/run_aivan_platform_whitelist_e2e.py
```

Each script prints a step-by-step trace of the agent actions, including generated drafts and approval status.

---

## CLI Reference

| Command | Description |
|---|---|
| `uv run aivan init` | Initialize local database and configuration. |
| `uv run aivan serve` | Start the web UI server. |
| `uv run aivan demo` | Run the core end-to-end demo. |
| `uv run aivan demo-marketplace` | Run the marketplace search demo. |
| `uv run aivan demo-risk-check` | Run supplier risk screening demo. |
| `uv run aivan test` | Run the test suite. |
| `uv run aivan import-suppliers` | Import suppliers from CSV or JSON. |
| `uv run aivan risk-check` | Run risk screening on a supplier. |
| `uv run aivan platforms` | List platform whitelist status. |
| `uv run aivan accounts` | List OpenClaw connected accounts. |

---

## API Reference

The AIVAN server exposes a REST API at `http://127.0.0.1:8765` by default. Server deployments may expose a different configured port.

### Events

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/openclaw/events` | Receive normalized OpenClaw events. |

### Projects

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/projects` | List all trade projects. |
| `GET` | `/api/projects/{id}` | Fetch a specific trade project. |
| `GET` | `/api/projects/{id}/events` | List events for a project. |
| `GET` | `/api/projects/{id}/drafts` | List drafts and notifications for a project. |
| `POST` | `/api/projects/{id}/strategy` | Update structured RFQ strategy. |
| `POST` | `/api/projects/{id}/run-gltg` | Run GLTG lead-time simulation. |

### User Preferences

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/user-preferences` | List learned user preferences. |
| `POST` | `/api/user-preferences/update` | Save/update user preference memory. |

### Suppliers

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/suppliers` | List suppliers in the configured database. |

### Drafts and Approval Gate

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/openclaw/drafts/{id}/approve` | Approve a pending draft message. |
| `POST` | `/api/openclaw/drafts/{id}/reject` | Reject a pending draft message. |

### Platforms

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/platforms` | List known platforms and whitelist status. |
| `GET` | `/api/platforms/suggestions` | List platform suggestions pending approval. |
| `POST` | `/api/platforms/suggestions/{id}/approve` | Approve a platform suggestion. |

### Accounts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/openclaw/accounts` | List OpenClaw connected accounts and status. |

---

## Lead-Time Model

AIVAN uses GLTG as the authoritative lead-time simulation model. GLTG may return percentile estimates such as P50, P80, and P90, depending on the simulation endpoint and available supplier context.

| Percentile | Meaning |
|---|---|
| P50 | Median expected lead time. |
| P80 | Conservative planning lead time. |
| P90 | High-confidence planning lead time for firm deadlines. |

When evaluating supplier options against a buyer's required delivery date, AIVAN should use the GLTG-recommended planning confidence level and preserve the raw GLTG result in the project audit trail.

---

## Repository Boundary

This repository owns:

```text
AIVAN runtime
AIVAN product rules
AIVAN OpenClaw Gateway plugin
openclaw-aivan AgentHarness
AIVAN ClawHub package candidate
AIVAN tests
AIVAN deployment docs
AIVAN CI
AIVAN RFQ / supplier-routing / lead-time capability
```

`abcdYi` is expected to contain AIVAN's full capability set later, after AIVAN is independently completed and stable.

`giraffe-agent` is the broader industrial procurement and execution framework. It may later absorb stable AIVAN capabilities, but it should not be the active development home for AIVAN runtime or OpenClaw Gateway fixes.

---

## ClawHub Publication Gate

The plugin is ready for ClawHub publication only after both conditions pass:

```text
1. Gateway P0 package/install/load/inspect/call tests pass.
2. Live WeChat business-flow acceptance passes end to end.
```

Dry run:

```bash
clawhub package publish integrations/openclaw-aivan-plugin --family code-plugin --dry-run
```

Publish:

```bash
clawhub package publish integrations/openclaw-aivan-plugin --family code-plugin
```

Optional skill listing:

```bash
clawhub skill publish skills/aivan-trade-salesperson \
  --slug aivan-trade-salesperson \
  --name "AIVAN Trade Salesperson" \
  --version 0.1.0 \
  --changelog "Initial AIVAN ClawHub skill listing"
```

Passing TypeScript build is not enough. The plugin is valid for public release only when OpenClaw Gateway can discover, install, load, inspect, call AIVAN, and complete the live business workflow.

---

## Security and Deployment Notes

Do not commit:

```text
.env files
API keys
server IPs
private keys
OpenClaw credentials
WeChat session material
database passwords
cookies
tokens
```

Public documentation should describe deployment topology without exposing private infrastructure details.

---

## Disclaimer

AIVAN is a decision-support and workflow-execution tool. It does not make final legal, credit, sanctions, trade compliance, or binding commercial decisions. Users are responsible for verifying supplier information and complying with applicable laws, platform rules, and contractual obligations.

---

## License

MIT License

Copyright (c) 2025 Giraffe Technology

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
