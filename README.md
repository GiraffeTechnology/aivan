# AIVAN — AI Trade Salesperson

`Python 3.11+` | `Standalone Product` | `OpenClaw Gateway` | `Multi-LLM` | `Human-in-the-loop`

AIVAN is a standalone AI trade salesperson assistant extracted from the broader Giraffe Agent architecture. It receives buyer inquiries, sources suppliers, screens risk, calculates lead times, and generates buyer options — with human approval for every outbound message.

---

## Current Milestone — Private-Domain RFQ Execution

AIVAN has moved beyond connectivity validation into the private-domain RFQ execution milestone.

Validated environment:

```text
Cloud server
Database: PostgreSQL
OpenClaw Gateway: v2026.6.10
AIVAN: v0.2.0
AIVAN runtime port: 8000
Plugin: openclaw-aivan
IM channel: WeChat bot via WeixinClawBot
```

Validated chain:

```text
WeChat message → WeixinClawBot response: PASS
OpenClaw Gateway running: PASS
openclaw-aivan plugin loaded: PASS
AIVAN server running: PASS
PostgreSQL available: PASS
```

This milestone proves that AIVAN can run as an independent product connected to a real OpenClaw Gateway and a live WeChat bot bridge, while creating auditable RFQ/project workflows:

```text
User IM command or customer email
→ OpenClaw Gateway
→ openclaw-aivan AgentHarness
→ AIVAN /api/openclaw/events
→ LLM strategy interpretation
→ Giraffe DB private-domain lookup
→ GLTG lead-time simulation
→ RFQ/project creation
→ pending supplier inquiry email drafts
→ user IM summary / approval request
→ approved email sent through OpenClaw email integration
```

---

## Product Positioning

Trading company salespeople handle a high volume of repetitive, time-sensitive tasks: parsing buyer inquiries, finding suitable suppliers, chasing quotations, comparing options, calculating feasibility, and drafting responses. Errors in any step — a missed risk flag, a misstated lead time, an unapproved message — can damage a business relationship or create legal exposure.

AIVAN is designed for exactly this workflow. It connects to existing IM, email, and marketplace accounts through OpenClaw and provides a structured, auditable process from inquiry to quote. The salesperson remains in control at every decision point that touches a counterparty. AIVAN does the heavy lifting — research, screening, calculation, drafting — while the human retains final authority over what gets sent and to whom.

AIVAN is developed first as a standalone product. Once stable, its capabilities can be forked, ported, or integrated into `abcdYi` and the broader `giraffe-agent` framework. AIVAN runtime and OpenClaw Gateway fixes belong in this repository first, not directly in `abcdYi` or `giraffe-agent`.

## AIVAN Product Boundary

AIVAN is the private-domain RFQ execution system. It is not a generic LLM chatbot, and it is not a redundant wrapper around the OpenClaw Qwen Gateway.

AIVAN owns RFQ/project workflow, trade event classification, private-domain context orchestration, Giraffe DB access, GLTG lead-time simulation calls, supplier-routing decisions, user preference memory usage, email draft creation, human approval, audit trails, and channel execution policy.

AIVAN does not own IM account login, WeChat/LINE/WhatsApp credential storage, CAPTCHA bypass, platform anti-bot bypass, LLM general-knowledge trade decisions, unapproved outbound communication, or final legal, credit, sanctions, and compliance decisions.

## Private-Domain Data and Giraffe DB

Giraffe DB is AIVAN's private-domain source of truth. AIVAN queries it for customers, customer preferences, suppliers, supplier relationships, historical RFQs, historical quotations, historical lead-time records, product categories, user preferences, approval history, draft revision history, and risk flags.

AIVAN must never ask an LLM to infer supplier facts, customer history, historical prices, historical lead times, or user preference memory from general knowledge. The LLM may reason over Giraffe DB context provided by AIVAN, but Giraffe DB remains the business fact source.

## GLTG Lead-Time Simulation

GLTG is the lead-time simulation model. AIVAN calls GLTG for P50/P80/P90 lead-time estimates, minimum feasible lead time, supplier-set feasibility, known-suppliers-first feasibility, public-bidding time cost, and fallback trigger recommendations.

The LLM may explain GLTG outputs in user-friendly language, but it must not replace GLTG calculations or invent lead-time estimates.

## LLM Strategy Intelligence

LLMs are used deeply for intent understanding, user preference interpretation, strategy translation, contextual reasoning over AIVAN-provided Giraffe DB and GLTG context, email summarization, customer/supplier message classification, draft generation, reason explanation, post-action review, and preference extraction.

Business decisions that affect workflow state use structured JSON outputs and deterministic fallbacks. AIVAN validates project attachment against database state and preserves the approval gate regardless of LLM output.

## User-Control IM vs Counterparty Outbound Channels

WeChat, LINE, WhatsApp, and similar IM channels are user-control channels. AIVAN uses them for user command input, notification, customer email summaries, approval requests, revision requests, status updates, and RFQ/project progress notifications.

Current counterparty outbound execution uses email. AIVAN creates pending email drafts for customer and supplier commercial communication, and sends them only after human approval.

AIVAN must not automatically send commercial messages to customers or suppliers through personal WeChat, LINE, WhatsApp, or similar personal IM channels. Future counterparty outbound channels must be official, API-permitted, auditable, authorized, and still subject to human approval.

## Email-First Outbound Execution

The current outbound execution chain is:

```text
AIVAN creates counterparty email draft
→ draft remains pending_approval
→ user approves or rejects
→ approved email is sent via OpenClaw/email integration
→ audit event and sent status are recorded
```

User-facing IM summaries may be sent as notifications through OpenClaw because they are user-control messages, not counterparty commercial messages.

---

## Repository Boundary

AIVAN owns:

```text
AIVAN runtime
AIVAN product rules
AIVAN OpenClaw Gateway plugin
openclaw-aivan AgentHarness
AIVAN ClawHub package
AIVAN tests
AIVAN deployment docs
AIVAN CI
AIVAN RFQ / supplier-routing / lead-time capability
```

`abcdYi` is expected to contain AIVAN's full capability set later, after AIVAN is independently completed and stable.

`giraffe-agent` is the broader industrial procurement and execution framework. It may later absorb stable AIVAN capabilities, but it should not be the active development home for AIVAN runtime or OpenClaw Gateway fixes.

---

## Key Product Rules

1. Human approval is required for ALL outbound messages. AIVAN never sends without user approval.
2. AIVAN never stores platform account passwords, cookies, or session tokens. All account connectivity is managed by OpenClaw.
3. AIVAN never bypasses login, CAPTCHA, anti-bot systems, access controls, rate limits, or platform rules.
4. A trusted platform does NOT mean every supplier on that platform is trusted. Risk screening is independent.
5. AIVAN does not make final legal, credit, sanctions, or compliance decisions.
6. AIVAN never hallucinates supplier facts. All supplier data is sourced or mock.
7. Never log API keys or credentials.
8. Giraffe DB is the private-domain source of truth.
9. GLTG is the lead-time simulation model.
10. LLMs provide controlled strategy intelligence, not business facts.
11. WeChat, LINE, WhatsApp, and similar IM channels are user-control channels.
12. Current counterparty outbound execution uses email.

---

## Architecture Overview

```text
                        ┌─────────────────────────────────────────────────┐
                        │              Trade Salesperson Agent             │
                        │                                                  │
  OpenClaw Events  ───► │  ┌──────────────────┐  ┌────────────────────┐  │
  (IM / Email /         │  │ Requirement Agent │  │ Supplier Inquiry   │  │
   Marketplace)         │  └──────────────────┘  │ Agent              │  │
                        │  ┌──────────────────┐  └────────────────────┘  │
                        │  │  Risk Screener   │  ┌────────────────────┐  │
                        │  └──────────────────┘  │ Lead Time          │  │
                        │  ┌──────────────────┐  │ Calculator         │  │
                        │  │ Buyer Option     │  └────────────────────┘  │
                        │  │ Agent            │                           │
                        │  └──────────────────┘                           │
                        └──────────────────┬──────────────────────────────┘
                                           │
                                           ▼
                              ┌────────────────────────┐
                              │   Human Approval Gate  │
                              │  (approve / reject)    │
                              └────────────┬───────────┘
                                           │
                                           ▼
                                  ┌─────────────────┐
                                  │  OpenClaw Send  │
                                  └─────────────────┘

  Storage
  ┌──────────────────────────────────────────────────────────┐
  │  SQLite for local dev │ PostgreSQL for server deployment │
  │  projects │ drafts │ events │ suppliers │ accounts      │
  │  platforms                                               │
  └──────────────────────────────────────────────────────────┘

  LLM Gateway
  ┌──────────────────────────────────────────────────────────┐
  │  mock (default) │ OpenAI │ Claude/Anthropic │ Gemini    │
  │  DeepSeek │ Qwen                                         │
  └──────────────────────────────────────────────────────────┘
```

All state (projects, drafts, events, suppliers, accounts, platforms) is stored in AIVAN's configured database. Local development defaults to SQLite; production/server deployments may use PostgreSQL. No outbound counterparty message is sent unless the human explicitly approves it.

---

## Install

```bash
git clone https://github.com/GiraffeTechnology/aivan.git
cd aivan
cp .env.example .env
# Edit .env if needed (defaults work with mock mode)
uv sync
uv run aivan init
```

No live credentials are required to install or run in mock mode.

---

## Quick Start

```bash
uv run aivan demo                    # Core E2E demo (mock mode)
uv run aivan demo-marketplace        # Marketplace search demo
uv run aivan demo-risk-check         # Risk screening demo
uv run aivan serve                   # Start web UI at http://127.0.0.1:8765/app
```

Open `http://127.0.0.1:8765/app` in your browser after running `serve`.

For server deployment, set `AIVAN_HOST`, `AIVAN_PORT`, and `AIVAN_DB_URL` explicitly. The cloud server milestone deployment runs AIVAN v0.1.0 on port `8000` with PostgreSQL.

---

## Environment Variables

All variables are set in `.env`. Copy `.env.example` to get started. The defaults work in mock mode without any live credentials.

### Core

| Variable | Default | Description |
|---|---|---|
| `AIVAN_ENV` | `local` | Runtime environment (`local`, `production`). |
| `AIVAN_HOST` | `127.0.0.1` | Host address for the web server. |
| `AIVAN_PORT` | `8765` | Port for the web server. Cloud server milestone deployment uses `8000`. |
| `AIVAN_DB_URL` | `sqlite:///./data/aivan.db` | Database URL. SQLite is the local default; PostgreSQL is supported for server deployment. |
| `AIVAN_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `AIVAN_REQUIRE_HUMAN_APPROVAL` | `true` | Enforce human approval gate for all outbound messages. |

Example PostgreSQL deployment URL:

```env
AIVAN_DB_URL=postgresql://aivan:<password>@127.0.0.1:5432/aivan
```

### OpenClaw

| Variable | Default | Description |
|---|---|---|
| `OPENCLAW_BASE_URL` | _(empty)_ | Base URL of the OpenClaw HTTP API. |
| `OPENCLAW_API_KEY` | _(empty)_ | API key for authenticating with OpenClaw. |
| `OPENCLAW_SEND_ENDPOINT` | `/messages/send` | Endpoint for sending messages via OpenClaw. |
| `OPENCLAW_MOCK_MODE` | `true` | Use mock OpenClaw responses (no live account needed). |
| `OPENCLAW_MARKETPLACE_ENABLED` | `true` | Enable marketplace search and contact via OpenClaw. |
| `OPENCLAW_MARKETPLACE_SEARCH_ENDPOINT` | `/marketplaces/search` | Endpoint for marketplace product search. |
| `OPENCLAW_MARKETPLACE_CONTACT_ENDPOINT` | `/marketplaces/contact` | Endpoint for contacting suppliers via marketplace. |

### LLM

| Variable | Default | Description |
|---|---|---|
| `AIVAN_LLM_PROVIDER` | `mock` | LLM provider: `mock`, `openai`, `anthropic`, `google`, `deepseek`, `qwen`. |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI API key (required when provider is `openai`). |
| `OPENAI_BASE_URL` | _(empty)_ | Optional custom base URL for OpenAI-compatible endpoints. |
| `OPENAI_MODEL` | _(empty)_ | OpenAI model name (e.g., `gpt-4o`). |
| `ANTHROPIC_API_KEY` | _(empty)_ | Anthropic API key (required when provider is `anthropic`). |
| `ANTHROPIC_MODEL` | _(empty)_ | Anthropic model name (e.g., `claude-opus-4-5`). |
| `GOOGLE_API_KEY` | _(empty)_ | Google API key (required when provider is `google`). |
| `GEMINI_MODEL` | _(empty)_ | Gemini model name (e.g., `gemini-2.0-flash`). |
| `DEEPSEEK_API_KEY` | _(empty)_ | DeepSeek API key (required when provider is `deepseek`). |
| `DEEPSEEK_BASE_URL` | _(empty)_ | DeepSeek API base URL. |
| `DEEPSEEK_MODEL` | _(empty)_ | DeepSeek model name (e.g., `deepseek-chat`). |
| `QWEN_API_KEY` | _(empty)_ | Qwen API key (required when provider is `qwen`). |
| `QWEN_BASE_URL` | _(empty)_ | Qwen API base URL. |
| `QWEN_MODEL` | _(empty)_ | Qwen model name (e.g., `qwen-plus`). |
| `AIVAN_LLM_TIMEOUT_SECONDS` | `30` | Request timeout for LLM API calls. |
| `AIVAN_LLM_MAX_RETRIES` | `2` | Maximum retries on LLM API failure. |
| `AIVAN_LLM_TEMPERATURE` | `0` | LLM temperature (0 = deterministic). |

### Alibaba / 1688

| Variable | Default | Description |
|---|---|---|
| `AIVAN_ALIBABA_MODE` | `mock` | Alibaba integration mode: `mock` or `live`. |
| `ALIBABA_API_BASE_URL` | _(empty)_ | Alibaba API base URL. |
| `ALIBABA_APP_KEY` | _(empty)_ | Alibaba app key. |
| `ALIBABA_APP_SECRET` | _(empty)_ | Alibaba app secret. |
| `ALIBABA_ACCESS_TOKEN` | _(empty)_ | Alibaba OAuth access token. |
| `ALIBABA_PLATFORM` | `1688\|alibaba_com\|auto` | Alibaba platform selector. |

### Web Search / Risk Screening

| Variable | Default | Description |
|---|---|---|
| `AIVAN_WEB_SEARCH_PROVIDER` | `mock` | Web search provider: `mock`, `openclaw`, `serp`, `bing`, `google_cse`. |
| `AIVAN_WEB_SEARCH_MAX_RESULTS` | `10` | Maximum results returned per search query. |
| `AIVAN_WEB_SEARCH_TIMEOUT_SECONDS` | `20` | Timeout for web search requests. |
| `OPENCLAW_SEARCH_ENABLED` | `true` | Allow OpenClaw to fulfill web search requests. |
| `OPENCLAW_SEARCH_ENDPOINT` | `/search/web` | OpenClaw endpoint for web search. |
| `SERP_API_KEY` | _(empty)_ | SerpAPI key (provider: `serp`). |
| `BING_SEARCH_API_KEY` | _(empty)_ | Bing Search API key (provider: `bing`). |
| `GOOGLE_CSE_API_KEY` | _(empty)_ | Google Custom Search Engine API key (provider: `google_cse`). |
| `GOOGLE_CSE_ID` | _(empty)_ | Google Custom Search Engine ID (provider: `google_cse`). |

### Risk Settings

| Variable | Default | Description |
|---|---|---|
| `AIVAN_ENABLE_UNKNOWN_SUPPLIER_RISK_SEARCH` | `true` | Run web search risk screening on unknown suppliers. |
| `AIVAN_BLOCK_CRITICAL_RISK_SUPPLIERS` | `false` | Block suppliers flagged as critical risk (requires manual override to proceed). |
| `AIVAN_REQUIRE_RISK_REVIEW_FOR_UNKNOWN_SUPPLIERS` | `true` | Require human review before proceeding with unknown suppliers. |

### Trade Settings

| Variable | Default | Description |
|---|---|---|
| `AIVAN_DEFAULT_MARGIN_RATE` | `0.15` | Default trading margin applied when generating buyer quotes (15%). |
| `AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER` | `true` | Do not reveal supplier name or contact to the buyer. |
| `AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER` | `true` | Do not reveal supplier unit price to the buyer. |

---

## Multi-LLM Configuration

Set `AIVAN_LLM_PROVIDER` in `.env` to switch providers. All providers use the same agent interface; only the `.env` configuration differs.

**Mock (default — no credentials required)**

```env
AIVAN_LLM_PROVIDER=mock
```

**OpenAI / ChatGPT-compatible**

```env
AIVAN_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
# Optional: point to any OpenAI-compatible endpoint
# OPENAI_BASE_URL=https://api.example.com/v1
```

**Anthropic / Claude**

```env
AIVAN_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-5
```

**Google / Gemini**

```env
AIVAN_LLM_PROVIDER=google
GOOGLE_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash
```

**DeepSeek**

```env
AIVAN_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

**Qwen (Alibaba Cloud)**

```env
AIVAN_LLM_PROVIDER=qwen
QWEN_API_KEY=sk-...
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

Common LLM tuning variables apply regardless of provider:

```env
AIVAN_LLM_TIMEOUT_SECONDS=30
AIVAN_LLM_MAX_RETRIES=2
AIVAN_LLM_TEMPERATURE=0
```

---

## Platform Whitelist

AIVAN maintains a trusted platform whitelist. **Alibaba** (`alibaba.com`, `1688.com`) and **AliExpress** (`aliexpress.com`) are built-in trusted platforms — AIVAN will search and contact suppliers on these platforms without additional prompting.

When AIVAN discovers a supplier on a platform that is not on the whitelist, it flags the platform for user approval before proceeding. The user sees the platform name and domain and can approve or reject it. Approved platforms are stored locally and remembered for future sessions.

**Important distinction:** a platform being on the trusted whitelist does not mean every supplier on that platform is trusted. Supplier-level risk screening (web search, fraud signals, blacklist checks) runs independently for every supplier, regardless of platform. Platform trust and supplier trust are evaluated separately.

To manage the platform whitelist:

```bash
uv run aivan platforms          # List current platforms and their trust status
```

Platform suggestions pending approval are available via the API at `GET /api/platforms/suggestions`.

---

## OpenClaw Integration

OpenClaw is the connectivity layer that gives AIVAN access to the salesperson's IM accounts (WeChat, WhatsApp), email accounts, and marketplace accounts (Alibaba, 1688, AliExpress). AIVAN communicates with OpenClaw through the native OpenClaw Gateway plugin and the AIVAN event API.

**What OpenClaw manages:**

- Inbound message delivery: OpenClaw receives messages from connected accounts and forwards them to AIVAN as events via `POST /api/openclaw/events`.
- Outbound message sending: when a draft is approved, AIVAN calls OpenClaw's send endpoint to deliver the message through the appropriate account.
- Marketplace search and supplier contact: AIVAN requests search results and sends supplier inquiries through OpenClaw's marketplace endpoints.
- Web search: AIVAN can route web search requests through OpenClaw when `OPENCLAW_SEARCH_ENABLED=true`.

**What AIVAN stores:**

AIVAN stores only account metadata (account ID, platform, display name, status). AIVAN never stores passwords, cookies, session tokens, or any credential material. All authentication state is managed entirely within OpenClaw.

In mock mode (`OPENCLAW_MOCK_MODE=true`), all OpenClaw interactions are simulated locally. No live accounts are needed for development or testing.

To view connected accounts:

```bash
curl http://127.0.0.1:8765/api/openclaw/accounts
```

### Native OpenClaw Gateway Plugin

AIVAN ships with a native OpenClaw Gateway plugin at:

```text
integrations/openclaw-aivan-plugin/
```

The plugin allows OpenClaw Gateway to discover, install, load, inspect, and call AIVAN directly.

Final plugin ID:

```text
openclaw-aivan
```

Package name:

```text
@giraffetechnology/openclaw-aivan
```

Runtime entry:

```text
./dist/index.js
```

Types entry:

```text
./dist/index.d.ts
```

Manifest:

```text
openclaw.plugin.json
```

The plugin registers an OpenClaw AgentHarness via `registerAgentHarness`, extracts the inbound prompt from OpenClaw runtime params, and forwards normalized events to:

```text
POST /api/openclaw/events
```

AIVAN preserves OpenClaw context fields such as:

- `project_id`
- `role_context`
- `conversation_id`
- `sender_id`
- `channel`

This context preservation is required for supplier-side replies to be routed to the correct trade project instead of being misclassified as new buyer inquiries.

---

## Human Approval Gate

Every counterparty outbound message drafted by AIVAN is saved to the local database with status `pending_approval`. No counterparty message is sent until a human explicitly approves it.

**Approval workflow:**

1. AIVAN drafts a message (supplier inquiry, buyer quote, follow-up, etc.) and stores it as a pending approval draft.
2. The salesperson reviews the draft in the web UI at `http://127.0.0.1:8765/app` or via the API.
3. The salesperson approves or rejects the draft.
4. On approval, AIVAN calls OpenClaw's send endpoint to deliver the message.
5. On rejection, the draft is marked rejected and no message is sent. The salesperson can edit and resubmit.

The approval requirement is controlled by `AIVAN_REQUIRE_HUMAN_APPROVAL=true` in `.env`. This variable is present for operational flexibility but the rule is non-negotiable in production use: AIVAN never sends without user approval.

**API endpoints for approval:**

```text
POST /api/openclaw/drafts/{id}/approve
POST /api/openclaw/drafts/{id}/reject
```

---

## Running Tests

```bash
uv run pytest
```

All tests run in mock mode. No live credentials, no external API calls, no OpenClaw connection required. Tests cover the full agent pipeline, risk screening, lead time calculation, platform whitelist logic, and approval gate enforcement.

### OpenClaw Gateway plugin tests

Run these tests before publishing or modifying the OpenClaw Gateway plugin:

```bash
python scripts/validate_clawhub_aivan_plugin.py
python scripts/run_aivan_openclaw_plugin_smoke_test.py --offline
python scripts/run_aivan_openclaw_install_smoke_test.py
python scripts/run_aivan_openclaw_gateway_p0_test.py
python scripts/run_aivan_openclaw_install_simulation.py
```

These tests verify the OpenClaw plugin package, local install lifecycle, Gateway inspection, ID alignment, and mock Gateway event routing.

### AgentHarness simulation test

From the plugin directory:

```bash
cd integrations/openclaw-aivan-plugin
npm install
npm run build
npx tsc
node test-gateway-harness.mjs
```

This test simulates the OpenClaw Gateway AgentHarness lifecycle and verifies that AIVAN receives a non-empty prompt and returns a valid `EmbeddedRunAttemptResult` shape.

---

## Running E2E Scripts

The following scripts run complete end-to-end scenarios in mock mode and are useful for understanding the full workflow or smoke-testing after changes.

```bash
uv run python scripts/run_aivan_e2e.py
uv run python scripts/run_aivan_private_domain_rfq_e2e.py
uv run python scripts/run_aivan_marketplace_e2e.py
uv run python scripts/run_aivan_unknown_supplier_risk_e2e.py
uv run python scripts/run_aivan_platform_whitelist_e2e.py
```

Each script prints a step-by-step trace of the agent's actions, including all drafts generated and their approval status.

---

## CLI Reference

| Command | Description |
|---|---|
| `uv run aivan init` | Initialize the local database and configuration. Run once after install. |
| `uv run aivan serve` | Start the web UI server at `http://127.0.0.1:8765/app`. |
| `uv run aivan demo` | Run the core end-to-end demo (buyer inquiry → supplier inquiry → quote). |
| `uv run aivan demo-marketplace` | Run the marketplace search demo. |
| `uv run aivan demo-risk-check` | Run the supplier risk screening demo. |
| `uv run aivan test` | Run the test suite (equivalent to `uv run pytest`). |
| `uv run aivan import-suppliers` | Import suppliers from a CSV or JSON file into the local database. |
| `uv run aivan risk-check` | Run risk screening on a specific supplier by name or ID. |
| `uv run aivan platforms` | List all platforms and their whitelist status. |
| `uv run aivan accounts` | List all OpenClaw connected accounts and their status. |

---

## API Reference

The AIVAN server exposes a REST API on `http://127.0.0.1:8765` by default. Server deployments may expose a different configured port, such as `8000`.

### Events

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/openclaw/events` | Receive an inbound event from OpenClaw (message, marketplace reply, etc.). |
| `POST` | `/api/rfq/create-from-event` | Create or update an RFQ/project from a normalized OpenClaw event. |

### Projects

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/projects` | List all trade projects. |
| `GET` | `/api/projects/{id}` | Fetch a specific trade project. |
| `GET` | `/api/projects/{id}/events` | List all events for a specific project. |
| `GET` | `/api/projects/{id}/drafts` | List all drafts and user notifications for a project. |
| `POST` | `/api/projects/{id}/strategy` | Update a project's structured RFQ strategy. |
| `POST` | `/api/projects/{id}/run-gltg` | Run GLTG lead-time simulation for a project. |

### User Preferences

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/user-preferences` | List learned user preferences, optionally filtered by `user_id`. |
| `POST` | `/api/user-preferences/update` | Save or update a user preference record in private-domain memory. |

### Suppliers

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/suppliers` | List all suppliers in the local database. |

### Drafts (Approval Gate)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/openclaw/drafts/{id}/approve` | Approve a pending draft message for sending. |
| `POST` | `/api/openclaw/drafts/{id}/reject` | Reject a pending draft message. |

### Platforms

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/platforms` | List all known platforms and their whitelist status. |
| `GET` | `/api/platforms/suggestions` | List platforms discovered during sourcing that are pending user approval. |
| `POST` | `/api/platforms/suggestions/{id}/approve` | Approve a platform suggestion (adds it to the local whitelist). |

### Accounts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/openclaw/accounts` | List all OpenClaw connected accounts and their status. |

---

## Lead Time Model

AIVAN calculates lead times using a probabilistic model that outputs three percentiles:

| Percentile | Meaning |
|---|---|
| P50 | Median expected lead time — 50% of orders complete by this date. |
| P80 | 80% confidence lead time — a more conservative estimate for planning. |
| P90 | 90% confidence lead time — use when the buyer's deadline is firm. |

When evaluating supplier options against a buyer's required delivery date, AIVAN uses P80 by default. The feasibility assessment tells the salesperson which suppliers can meet the deadline and with what confidence level.

---

## OpenClaw Gateway Plugin

AIVAN includes a native OpenClaw Gateway plugin.

Plugin path:

```bash
integrations/openclaw-aivan-plugin/
```

Final plugin ID:

```text
openclaw-aivan
```

Package name:

```text
@giraffetechnology/openclaw-aivan
```

Tested milestone environment:

```text
Cloud server
OpenClaw Gateway: v2026.6.10
AIVAN: v0.1.0
AIVAN runtime port: 8000
Database: PostgreSQL
WeChat bridge: WeixinClawBot
```

Compatibility target:

```text
OpenClaw >=2026.3.22
```

### Install the plugin locally

From the plugin directory:

```bash
cd integrations/openclaw-aivan-plugin
npm install
npm run build
npm run typecheck
npx tsc
```

Then install through OpenClaw:

```bash
openclaw plugins install . --force
```

Or install from an absolute path:

```bash
openclaw plugins install /opt/giraffe/aivan/integrations/openclaw-aivan-plugin --force
```

### Verify Gateway installation

```bash
openclaw plugins list --verbose
openclaw plugins inspect openclaw-aivan --runtime --json
```

Expected result:

```text
AIVAN OpenClaw Bridge (openclaw-aivan) enabled
status: loaded
activated: true
diagnostics: []
```

### Plugin package metadata

| Field | Value |
|---|---|
| Package name | `@giraffetechnology/openclaw-aivan` |
| Plugin ID | `openclaw-aivan` |
| Runtime entry | `./dist/index.js` |
| Types entry | `./dist/index.d.ts` |
| Manifest | `openclaw.plugin.json` |
| OpenClaw compatibility | `>=2026.3.22` |
| Tested OpenClaw version | `2026.6.10` |
| Install path | `/root/.openclaw/extensions/openclaw-aivan` |

### Gateway event routing

The plugin registers an OpenClaw AgentHarness and forwards normalized events to AIVAN.

Example supplier-side event:

```json
{
  "source": "openclaw",
  "channel": "wechat",
  "conversation_id": "conv-project-001",
  "sender_id": "supplier-weixin-001",
  "sender_display_name": "Supplier Co.",
  "message_text": "We can quote 10000 shirts, cotton poplin, lead time 21 days, MOQ 10000 pcs.",
  "message_type": "text",
  "project_id": "test-project-001",
  "role_context": {
    "side": "supplier",
    "role": "seller"
  },
  "mode": "auto"
}
```

`project_id` and `role_context` must be preserved. This allows AIVAN to classify the message as a supplier reply and attach it to the correct trade project.

### P0 Gateway acceptance tests

Run these tests before publishing or merging changes to the plugin:

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

openclaw plugins validate --entry ./dist/index.js
openclaw plugins build --entry ./dist/index.js --check
openclaw plugins install . --force
openclaw plugins list --verbose
openclaw plugins inspect openclaw-aivan --runtime --json
```

Required acceptance criteria:

- `npm run build` passes.
- `npm run typecheck` passes.
- `npx tsc` passes.
- `openclaw plugins validate --entry ./dist/index.js` passes.
- `openclaw plugins build --entry ./dist/index.js --check` passes.
- `openclaw plugins install . --force` passes.
- `openclaw plugins inspect openclaw-aivan --runtime --json` returns `status: loaded`.
- Gateway can call AIVAN.
- WeChat / OpenClaw event reaches AIVAN.
- `project_id` is preserved when present.
- `role_context` is preserved when present.
- Supplier reply is not misclassified as a new buyer request.

### P0 verification evidence

PR #3 and the cloud server deployment verified the following production-critical flow:

```text
Cloud server environment: PASS
PostgreSQL database: PASS
OpenClaw Gateway v2026.6.10 running: PASS
AIVAN v0.1.0 running on port 8000: PASS
openclaw-aivan plugin loaded: PASS
WeChat bot connected: PASS
WeChat message receive/send path: PASS
WeChat message → WeixinClawBot response: PASS
```

Original Gateway registration failure fixed:

```text
TypeError: Cannot read properties of undefined (reading 'trim')
```

Final OpenClaw Gateway fix:

- Use `registerAgentHarness` instead of the incompatible `registerInteractiveHandler` path.
- Return a valid AgentHarness support object from `supports()`.
- Extract the inbound prompt from `params.prompt` first, with fallback fields for compatibility.
- Return a valid `EmbeddedRunAttemptResult` / AgentHarness attempt result.
- Preserve `project_id` and `role_context` from OpenClaw context when present.
- Forward events to AIVAN through `POST /api/openclaw/events`.
- Keep Gateway stable when AIVAN is offline or when the prompt is empty/malformed.
- Point `main`, `types`, and `exports` to compiled `dist/` files.
- Include `openclaw.plugin.json` with `id`, `configSchema`, and startup activation metadata.

### Next milestone: business-flow acceptance

The current milestone proves production connectivity. The next acceptance target is business execution:

```text
Real WeChat procurement inquiry
→ OpenClaw Gateway
→ openclaw-aivan AgentHarness
→ AIVAN event API
→ RFQ / project creation
→ pending human-approved response draft
→ approved reply sent through WeChat
```

Example test message:

```text
帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华
```

Expected result:

```text
AIVAN creates an RFQ / project
AIVAN stores the event and context
AIVAN generates a pending draft response
No outbound message is sent without human approval
```

### ClawHub publication

The plugin is ready for ClawHub publication only after Gateway P0 tests and business-flow acceptance both pass.

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

Important: passing TypeScript build is not enough. The plugin is considered valid only when OpenClaw Gateway can discover, install, load, inspect, and call AIVAN.

---

## Disclaimer

AIVAN is a decision-support tool. It does not make final legal, credit, sanctions, trade compliance, or binding commercial decisions. Users are responsible for verifying supplier information and compliance with applicable laws and regulations.

---

## License

MIT License

Copyright (c) 2025 Giraffe Technology

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
