# AIVEN — AI Trade Salesperson

`Python 3.11+` | `Local-first` | `Multi-LLM` | `Human-in-the-loop`

AIVEN is a local-first AI trade salesperson assistant. It receives buyer inquiries, sources suppliers, screens risk, calculates lead times, and generates buyer options — with human approval for every outbound message.

---

## Product Positioning

Trading company salespeople handle a high volume of repetitive, time-sensitive tasks: parsing buyer inquiries, finding suitable suppliers, chasing quotations, comparing options, calculating feasibility, and drafting responses. Errors in any step — a missed risk flag, a misstated lead time, an unapproved message — can damage a business relationship or create legal exposure.

AIVEN is designed for exactly this workflow. It runs locally on the salesperson's machine, connects to their existing IM, email, and marketplace accounts via OpenClaw, and provides a structured, auditable process from inquiry to quote. The salesperson remains in control at every decision point that touches a counterparty. AIVEN does the heavy lifting — research, screening, calculation, drafting — while the human retains final authority over what gets sent and to whom.

---

## Key Product Rules

1. Human approval is required for ALL outbound messages. AIVEN never sends without user approval.
2. AIVEN never stores platform account passwords, cookies, or session tokens. All account connectivity is managed by OpenClaw.
3. AIVEN never bypasses login, CAPTCHA, anti-bot systems, access controls, rate limits, or platform rules.
4. A trusted platform does NOT mean every supplier on that platform is trusted. Risk screening is independent.
5. AIVEN does not make final legal, credit, sanctions, or compliance decisions.
6. AIVEN never hallucinate supplier facts. All supplier data is sourced or mock.
7. Never log API keys or credentials.

---

## Architecture Overview

```
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

  Local SQLite DB
  ┌──────────────────────────────────────────────────────────┐
  │  projects │ drafts │ events │ suppliers │ accounts │     │
  │  platforms                                               │
  └──────────────────────────────────────────────────────────┘

  LLM Gateway
  ┌──────────────────────────────────────────────────────────┐
  │  mock (default) │ OpenAI │ Claude/Anthropic │ Gemini    │
  │  DeepSeek │ Qwen                                         │
  └──────────────────────────────────────────────────────────┘
```

All state (projects, drafts, events, suppliers, accounts, platforms) is stored in a local SQLite database. No data leaves the machine unless the human explicitly approves an outbound message.

---

## Install

```bash
git clone https://github.com/GiraffeTechnology/aiven.git
cd aiven
cp .env.example .env
# Edit .env if needed (defaults work with mock mode)
uv sync
uv run aiven init
```

No live credentials are required to install or run in mock mode.

---

## Quick Start

```bash
uv run aiven demo                    # Core E2E demo (mock mode)
uv run aiven demo-marketplace        # Marketplace search demo
uv run aiven demo-risk-check         # Risk screening demo
uv run aiven serve                   # Start web UI at http://127.0.0.1:8765/app
```

Open `http://127.0.0.1:8765/app` in your browser after running `serve`.

---

## Environment Variables

All variables are set in `.env`. Copy `.env.example` to get started. The defaults work in mock mode without any live credentials.

### Core

| Variable | Default | Description |
|---|---|---|
| `AIVEN_ENV` | `local` | Runtime environment (`local`, `production`). |
| `AIVEN_HOST` | `127.0.0.1` | Host address for the web server. |
| `AIVEN_PORT` | `8765` | Port for the web server. |
| `AIVEN_DB_URL` | `sqlite:///./data/aiven.db` | SQLite database URL. |
| `AIVEN_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `AIVEN_REQUIRE_HUMAN_APPROVAL` | `true` | Enforce human approval gate for all outbound messages. |

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
| `AIVEN_LLM_PROVIDER` | `mock` | LLM provider: `mock`, `openai`, `anthropic`, `google`, `deepseek`, `qwen`. |
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
| `AIVEN_LLM_TIMEOUT_SECONDS` | `30` | Request timeout for LLM API calls. |
| `AIVEN_LLM_MAX_RETRIES` | `2` | Maximum retries on LLM API failure. |
| `AIVEN_LLM_TEMPERATURE` | `0` | LLM temperature (0 = deterministic). |

### Alibaba / 1688

| Variable | Default | Description |
|---|---|---|
| `AIVEN_ALIBABA_MODE` | `mock` | Alibaba integration mode: `mock` or `live`. |
| `ALIBABA_API_BASE_URL` | _(empty)_ | Alibaba API base URL. |
| `ALIBABA_APP_KEY` | _(empty)_ | Alibaba app key. |
| `ALIBABA_APP_SECRET` | _(empty)_ | Alibaba app secret. |
| `ALIBABA_ACCESS_TOKEN` | _(empty)_ | Alibaba OAuth access token. |
| `ALIBABA_PLATFORM` | `1688\|alibaba_com\|auto` | Alibaba platform selector. |

### Web Search / Risk Screening

| Variable | Default | Description |
|---|---|---|
| `AIVEN_WEB_SEARCH_PROVIDER` | `mock` | Web search provider: `mock`, `openclaw`, `serp`, `bing`, `google_cse`. |
| `AIVEN_WEB_SEARCH_MAX_RESULTS` | `10` | Maximum results returned per search query. |
| `AIVEN_WEB_SEARCH_TIMEOUT_SECONDS` | `20` | Timeout for web search requests. |
| `OPENCLAW_SEARCH_ENABLED` | `true` | Allow OpenClaw to fulfill web search requests. |
| `OPENCLAW_SEARCH_ENDPOINT` | `/search/web` | OpenClaw endpoint for web search. |
| `SERP_API_KEY` | _(empty)_ | SerpAPI key (provider: `serp`). |
| `BING_SEARCH_API_KEY` | _(empty)_ | Bing Search API key (provider: `bing`). |
| `GOOGLE_CSE_API_KEY` | _(empty)_ | Google Custom Search Engine API key (provider: `google_cse`). |
| `GOOGLE_CSE_ID` | _(empty)_ | Google Custom Search Engine ID (provider: `google_cse`). |

### Risk Settings

| Variable | Default | Description |
|---|---|---|
| `AIVEN_ENABLE_UNKNOWN_SUPPLIER_RISK_SEARCH` | `true` | Run web search risk screening on unknown suppliers. |
| `AIVEN_BLOCK_CRITICAL_RISK_SUPPLIERS` | `false` | Block suppliers flagged as critical risk (requires manual override to proceed). |
| `AIVEN_REQUIRE_RISK_REVIEW_FOR_UNKNOWN_SUPPLIERS` | `true` | Require human review before proceeding with unknown suppliers. |

### Trade Settings

| Variable | Default | Description |
|---|---|---|
| `AIVEN_DEFAULT_MARGIN_RATE` | `0.15` | Default trading margin applied when generating buyer quotes (15%). |
| `AIVEN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER` | `true` | Do not reveal supplier name or contact to the buyer. |
| `AIVEN_HIDE_SUPPLIER_PRICE_FROM_BUYER` | `true` | Do not reveal supplier unit price to the buyer. |

---

## Multi-LLM Configuration

Set `AIVEN_LLM_PROVIDER` in `.env` to switch providers. All providers use the same agent interface; only the `.env` configuration differs.

**Mock (default — no credentials required)**

```env
AIVEN_LLM_PROVIDER=mock
```

**OpenAI / ChatGPT-compatible**

```env
AIVEN_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
# Optional: point to any OpenAI-compatible endpoint
# OPENAI_BASE_URL=https://api.example.com/v1
```

**Anthropic / Claude**

```env
AIVEN_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-5
```

**Google / Gemini**

```env
AIVEN_LLM_PROVIDER=google
GOOGLE_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash
```

**DeepSeek**

```env
AIVEN_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

**Qwen (Alibaba Cloud)**

```env
AIVEN_LLM_PROVIDER=qwen
QWEN_API_KEY=sk-...
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

Common LLM tuning variables apply regardless of provider:

```env
AIVEN_LLM_TIMEOUT_SECONDS=30
AIVEN_LLM_MAX_RETRIES=2
AIVEN_LLM_TEMPERATURE=0
```

---

## Platform Whitelist

AIVEN maintains a trusted platform whitelist. **Alibaba** (`alibaba.com`, `1688.com`) and **AliExpress** (`aliexpress.com`) are built-in trusted platforms — AIVEN will search and contact suppliers on these platforms without additional prompting.

When AIVEN discovers a supplier on a platform that is not on the whitelist, it flags the platform for user approval before proceeding. The user sees the platform name and domain and can approve or reject it. Approved platforms are stored locally and remembered for future sessions.

**Important distinction:** a platform being on the trusted whitelist does not mean every supplier on that platform is trusted. Supplier-level risk screening (web search, fraud signals, blacklist checks) runs independently for every supplier, regardless of platform. Platform trust and supplier trust are evaluated separately.

To manage the platform whitelist:

```bash
uv run aiven platforms          # List current platforms and their trust status
```

Platform suggestions pending approval are available via the API at `GET /api/platforms/suggestions`.

---

## OpenClaw Integration

OpenClaw is the connectivity layer that gives AIVEN access to the salesperson's IM accounts (WeChat, WhatsApp), email accounts, and marketplace accounts (Alibaba, 1688, AliExpress). AIVEN communicates with OpenClaw via a local HTTP API.

**What OpenClaw manages:**

- Inbound message delivery: OpenClaw receives messages from connected accounts and forwards them to AIVEN as events via `POST /api/openclaw/events`.
- Outbound message sending: when a draft is approved, AIVEN calls OpenClaw's send endpoint to deliver the message through the appropriate account.
- Marketplace search and supplier contact: AIVEN requests search results and sends supplier inquiries through OpenClaw's marketplace endpoints.
- Web search: AIVEN can route web search requests through OpenClaw when `OPENCLAW_SEARCH_ENABLED=true`.

**What AIVEN stores:**

AIVEN stores only account metadata (account ID, platform, display name, status). AIVEN never stores passwords, cookies, session tokens, or any credential material. All authentication state is managed entirely within OpenClaw.

In mock mode (`OPENCLAW_MOCK_MODE=true`), all OpenClaw interactions are simulated locally. No live accounts are needed for development or testing.

To view connected accounts:

```bash
curl http://127.0.0.1:8765/api/openclaw/accounts
```

---

## Human Approval Gate

Every outbound message drafted by AIVEN is saved to the local database with status `pending`. No message is sent until a human explicitly approves it.

**Approval workflow:**

1. AIVEN drafts a message (supplier inquiry, buyer quote, follow-up, etc.) and stores it as a pending draft.
2. The salesperson reviews the draft in the web UI at `http://127.0.0.1:8765/app` or via the API.
3. The salesperson approves or rejects the draft.
4. On approval, AIVEN calls OpenClaw's send endpoint to deliver the message.
5. On rejection, the draft is marked rejected and no message is sent. The salesperson can edit and resubmit.

The approval requirement is controlled by `AIVEN_REQUIRE_HUMAN_APPROVAL=true` in `.env`. This variable is present for operational flexibility but the rule is non-negotiable in production use: AIVEN never sends without user approval.

**API endpoints for approval:**

```
POST /api/openclaw/drafts/{id}/approve
POST /api/openclaw/drafts/{id}/reject
```

---

## Running Tests

```bash
uv run pytest
```

All tests run in mock mode. No live credentials, no external API calls, no OpenClaw connection required. Tests cover the full agent pipeline, risk screening, lead time calculation, platform whitelist logic, and approval gate enforcement.

---

## Running E2E Scripts

The following scripts run complete end-to-end scenarios in mock mode and are useful for understanding the full workflow or smoke-testing after changes.

```bash
uv run python scripts/run_aiven_e2e.py
uv run python scripts/run_aiven_marketplace_e2e.py
uv run python scripts/run_aiven_unknown_supplier_risk_e2e.py
uv run python scripts/run_aiven_platform_whitelist_e2e.py
```

Each script prints a step-by-step trace of the agent's actions, including all drafts generated and their approval status.

---

## CLI Reference

| Command | Description |
|---|---|
| `uv run aiven init` | Initialize the local database and configuration. Run once after install. |
| `uv run aiven serve` | Start the web UI server at `http://127.0.0.1:8765/app`. |
| `uv run aiven demo` | Run the core end-to-end demo (buyer inquiry → supplier inquiry → quote). |
| `uv run aiven demo-marketplace` | Run the marketplace search demo. |
| `uv run aiven demo-risk-check` | Run the supplier risk screening demo. |
| `uv run aiven test` | Run the test suite (equivalent to `uv run pytest`). |
| `uv run aiven import-suppliers` | Import suppliers from a CSV or JSON file into the local database. |
| `uv run aiven risk-check` | Run risk screening on a specific supplier by name or ID. |
| `uv run aiven platforms` | List all platforms and their whitelist status. |
| `uv run aiven accounts` | List all OpenClaw connected accounts and their status. |

---

## API Reference

The AIVEN server exposes a REST API on `http://127.0.0.1:8765`. All endpoints return JSON.

### Events

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/openclaw/events` | Receive an inbound event from OpenClaw (message, marketplace reply, etc.). |

### Projects

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/projects` | List all trade projects. |
| `GET` | `/api/projects/{id}/events` | List all events for a specific project. |

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

AIVEN calculates lead times using a probabilistic model that outputs three percentiles:

| Percentile | Meaning |
|---|---|
| P50 | Median expected lead time — 50% of orders complete by this date. |
| P80 | 80% confidence lead time — a more conservative estimate for planning. |
| P90 | 90% confidence lead time — use when the buyer's deadline is firm. |

When evaluating supplier options against a buyer's required delivery date, AIVEN uses P80 by default. The feasibility assessment tells the salesperson which suppliers can meet the deadline and with what confidence level.

---

## Disclaimer

AIVEN is a decision-support tool. It does not make final legal, credit, sanctions, trade compliance, or binding commercial decisions. Users are responsible for verifying supplier information and compliance with applicable laws and regulations.

---

## License

MIT License

Copyright (c) 2025 Giraffe Technology

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
