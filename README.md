# AIVAN — AI Trade Salesperson

`Python 3.11+` | `AIVAN v0.2.0` | `Standalone Product` | `OpenClaw Gateway` | `Multi-LLM` | `Giraffe DB / GPM` | `GLTG` | `Human-in-the-loop`

AIVAN is a standalone AI trade salesperson assistant for private-domain RFQ execution. It receives buyer inquiries from IM, email, marketplace, or OpenClaw-controlled channels; structures the requirement; looks up private business context; screens supplier risk; calls GLTG for lead-time simulation; drafts buyer/supplier messages; and keeps a mandatory human approval gate before any counterparty-facing message is sent.

AIVAN is not a generic chatbot. It is an auditable trade-execution system for trading companies, merchandisers, and cross-border sourcing teams.

---

## Current Status

Status snapshot: **2026-06-30**.

| Area | Status | Notes |
|---|---:|---|
| Local mock-mode install | PASS | No live credentials required. |
| Local AIVAN demos | PASS | RFQ, marketplace, risk, whitelist, and approval-gate flows run in mock mode. |
| AIVAN runtime / API | PASS | FastAPI app exposes `/app`, `/invoke`, `/api/openclaw/events`, RFQ, project, draft, platform, account, GPM, and health endpoints. |
| Local state DB | PASS | SQLite for local development; PostgreSQL can be used through `AIVAN_DB_URL` in server deployment. |
| OpenClaw plugin package | PASS | `@giraffetechnology/openclaw-aivan` builds and typechecks as a Gateway plugin. |
| Gateway package/install/load/inspect path | PASS | P0 plugin lifecycle scripts are present and should be run before every release. |
| Live WeChat → OpenClaw/AIVAN invocation | PASS | A real WeChat message reached the AIVAN/OpenClaw invocation path. |
| Configured model/provider availability | BLOCKED | The selected backend model/provider must be available in the live environment. |
| Live RFQ business-flow acceptance | BLOCKED | AIVAN must create/update an RFQ/project and generate a pending approval draft from a real WeChat command. |
| ClawHub production publication | NOT READY | Requires both Gateway P0 acceptance and live business-flow acceptance. |

The main blocker is no longer basic WeChat connectivity. The current P0 blocker is **backend dependency readiness**: the configured LLM/model provider and supporting services must be available so a live command can complete the RFQ workflow.

Required live acceptance path:

```text
Real WeChat command
→ WeixinClawBot / OpenClaw Gateway
→ openclaw-aivan plugin
→ AIVAN /invoke or /api/openclaw/events
→ configured model/provider available
→ RFQ/project created or updated
→ inbound event and OpenClaw context stored
→ pending draft or structured approval request created
→ no outbound counterparty message sent without human approval
```

Example acceptance command:

```text
帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华
```

---

## Product Positioning

Trading company salespeople and merchandisers repeatedly parse buyer requirements, identify missing fields, route inquiries to suppliers, compare quotations, calculate delivery feasibility, draft replies, and manage follow-ups. AIVAN automates the structured execution layer while keeping the human operator responsible for approval, judgment, and legal/commercial commitments.

AIVAN is developed first as an independent product. Stable capabilities may later be ported into `abcdYi` or the broader `giraffe-agent` framework, but active AIVAN runtime, OpenClaw Gateway, RFQ, GLTG, approval-gate, and live-channel fixes belong in this repository first.

---

## Product Boundary

AIVAN owns:

```text
RFQ/project workflow
trade event classification
private-domain context orchestration
Giraffe DB / GPM integration
GLTG lead-time simulation calls
supplier routing logic
supplier risk screening
user preference memory usage
draft generation
human approval workflow
audit trail generation
OpenClaw event ingestion
channel execution policy
```

AIVAN does not own:

```text
IM account login
WeChat/LINE/WhatsApp credential storage
CAPTCHA bypass
platform anti-bot bypass
unapproved outbound communication
final legal, credit, sanctions, or compliance decisions
```

OpenClaw owns channel connectivity. AIVAN owns trade-execution logic.

---

## Non-Negotiable Product Rules

1. Human approval is required for all counterparty outbound messages.
2. AIVAN never stores platform passwords, cookies, session tokens, or credential material.
3. AIVAN never bypasses login, CAPTCHA, anti-bot systems, access controls, rate limits, or platform rules.
4. A trusted marketplace does not mean every supplier on that marketplace is trusted.
5. Supplier-level risk screening is independent from platform-level trust.
6. AIVAN does not make final legal, credit, sanctions, or trade-compliance decisions.
7. AIVAN must not hallucinate supplier facts, customer history, price history, lead-time history, or user preference memory.
8. Giraffe DB / GPM is the private-domain business context source.
9. GLTG is the lead-time simulation source.
10. LLMs provide controlled strategy intelligence; they are not the source of private business facts.
11. WeChat, LINE, WhatsApp, and similar IM channels are user-control channels.
12. Current counterparty outbound execution is approval-first and email/OpenClaw-policy controlled unless an official, API-permitted, auditable channel is implemented.
13. Never log API keys, credentials, cookies, tokens, private keys, or private server secrets.

---

## Architecture

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
      AIVAN /invoke or /api/openclaw/events
                │
                ├── RFQ execution pipeline
                ├── Requirement Agent
                ├── Supplier Inquiry Agent
                ├── Supplier Risk Screener
                ├── Buyer Option Agent
                ├── Giraffe DB / GPM context lookup
                ├── GLTG lead-time simulation client
                └── LLM strategy interpretation
                │
                ▼
        Human Approval Gate
                │
                ▼
  Approved outbound execution through OpenClaw/email policy
```

Storage split:

| Layer | Purpose | Configuration |
|---|---|---|
| AIVAN local state DB | Projects, events, drafts, suppliers, accounts, approvals, risk flags, local workflow state. | `AIVAN_DB_URL` |
| Giraffe DB / GPM | Private-domain business context and execution packets. | `GIRAFFE_DB_BASE_URL` |
| GLTG | Standalone lead-time simulation service. | `GLTG_API_BASE_URL` |

If `GIRAFFE_DB_BASE_URL` is empty, GPM can fall back to an in-memory mode for development. Do not treat that fallback as production persistence.

---

## Install

```bash
git clone https://github.com/GiraffeTechnology/aivan.git
cd aivan
cp .env.example .env
uv sync
uv run aivan init
```

No live credentials are required for mock mode.

---

## Quick Start

```bash
uv run aivan demo                    # Core RFQ demo in mock mode
uv run aivan demo-marketplace        # Marketplace sourcing demo in mock mode
uv run aivan demo-risk-check         # Supplier risk-screening demo
uv run aivan serve                   # Start local web UI
```

Open the local web UI:

```text
http://127.0.0.1:8765/app
```

Check health:

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/api/health
```

For server deployment, explicitly set:

```env
AIVAN_ENV=production
AIVAN_HOST=0.0.0.0
AIVAN_PORT=8765
AIVAN_DB_URL=postgresql://aivan:<password>@127.0.0.1:5432/aivan
AIVAN_REQUIRE_HUMAN_APPROVAL=true
```

---

## Environment Variables

All variables are loaded from `.env`. Start from `.env.example`.

### Core runtime

| Variable | Default | Description |
|---|---|---|
| `AIVAN_ENV` | `local` | Runtime environment. |
| `AIVAN_HOST` | `127.0.0.1` | FastAPI host. |
| `AIVAN_PORT` | `8765` | FastAPI port. |
| `AIVAN_DB_URL` | `sqlite:///./data/aivan.db` | AIVAN workflow database. Use PostgreSQL in server deployment. |
| `AIVAN_LOG_LEVEL` | `INFO` | Logging level. |
| `AIVAN_REQUIRE_HUMAN_APPROVAL` | `true` | Enforce approval gate for outbound actions. |
| `AIVAN_API_KEY` | empty | Optional API key for protected endpoints. When set, callers must send `X-AIVAN-API-Key`. |

### Giraffe DB / GPM

| Variable | Default | Description |
|---|---|---|
| `GIRAFFE_DB_BASE_URL` | empty | External giraffe-db base URL. Empty means development fallback. |
| `GPM_LLM_RUNTIME_MODE` | `mock` | `mock` or `live`; live mode uses the configured AIVAN LLM provider. |
| `AIVAN_AUTH_SECRET` | empty | HMAC secret for bearer-token workflows. Required for production-grade auth. |
| `GIRAFFE_DB_SERVICE_AUTH_SECRET` | empty | Shared service-to-service secret for AIVAN ↔ giraffe-db calls. |

### OpenClaw

| Variable | Default | Description |
|---|---|---|
| `OPENCLAW_BASE_URL` | empty | OpenClaw HTTP API base URL. |
| `OPENCLAW_API_KEY` | empty | API key for OpenClaw API calls. |
| `OPENCLAW_SEND_ENDPOINT` | `/messages/send` | OpenClaw outbound message endpoint. |
| `OPENCLAW_MOCK_MODE` | `true` | Use mock OpenClaw responses. |
| `OPENCLAW_MARKETPLACE_ENABLED` | `true` | Enable marketplace search/contact through OpenClaw policy. |
| `OPENCLAW_MARKETPLACE_SEARCH_ENDPOINT` | `/marketplaces/search` | Marketplace search endpoint. |
| `OPENCLAW_MARKETPLACE_CONTACT_ENDPOINT` | `/marketplaces/contact` | Marketplace contact endpoint. |
| `OPENCLAW_SEARCH_ENABLED` | `true` | Allow OpenClaw to fulfill web-search requests when configured. |
| `OPENCLAW_SEARCH_ENDPOINT` | `/search/web` | OpenClaw web-search endpoint. |

### LLM providers

| Variable | Default | Description |
|---|---|---|
| `AIVAN_LLM_PROVIDER` | `mock` | `mock`, `openai`, `anthropic`, `google`, `deepseek`, `qwen`, or `ollama`. |
| `OPENAI_API_KEY` | empty | Required when provider is `openai`. |
| `OPENAI_BASE_URL` | empty | Optional OpenAI-compatible endpoint. |
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
| `OLLAMA_MODEL` | `qwen3.5:0.8b` | Local Ollama model name. Must exactly match `ollama list`. |
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

Ollama example:

```bash
ollama list
```

```env
AIVAN_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=<exact-model-name-from-ollama-list>
```

### Alibaba / 1688, search, risk, trade, and GLTG

| Variable | Default | Description |
|---|---|---|
| `AIVAN_ALIBABA_MODE` | `mock` | `mock` or `live`. |
| `ALIBABA_API_BASE_URL` | empty | Alibaba API base URL. |
| `ALIBABA_APP_KEY` | empty | Alibaba app key. |
| `ALIBABA_APP_SECRET` | empty | Alibaba app secret. |
| `ALIBABA_ACCESS_TOKEN` | empty | Alibaba OAuth access token. |
| `ALIBABA_PLATFORM` | `1688\|alibaba_com\|auto` | Alibaba platform selector. |
| `AIVAN_WEB_SEARCH_PROVIDER` | `mock` | Web-search provider mode. |
| `AIVAN_WEB_SEARCH_MAX_RESULTS` | `10` | Maximum web-search results. |
| `AIVAN_WEB_SEARCH_TIMEOUT_SECONDS` | `20` | Web-search timeout. |
| `AIVAN_ENABLE_UNKNOWN_SUPPLIER_RISK_SEARCH` | `true` | Run web-search risk screening on unknown suppliers. |
| `AIVAN_BLOCK_CRITICAL_RISK_SUPPLIERS` | `false` | Block critical-risk suppliers unless manually overridden. |
| `AIVAN_REQUIRE_RISK_REVIEW_FOR_UNKNOWN_SUPPLIERS` | `true` | Require review before unknown suppliers are used. |
| `AIVAN_DEFAULT_MARGIN_RATE` | `0.15` | Default trading margin. |
| `AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER` | `true` | Do not reveal supplier identity to buyer. |
| `AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER` | `true` | Do not reveal supplier unit price to buyer. |
| `GLTG_API_BASE_URL` | `http://localhost:8090` | Standalone GLTG service URL. |
| `GLTG_API_TIMEOUT_SECONDS` | `30` | GLTG request timeout. |

AIVAN must not locally invent lead-time results when GLTG is configured as the authoritative source.

---

## OpenClaw Integration

OpenClaw is the channel-connectivity layer. It manages account login/session state, inbound delivery, outbound execution after approval, marketplace/search channel access, and channel-specific policy.

AIVAN stores only account metadata:

```text
account ID
platform
display name
status
project/event/draft linkage
permissions metadata
```

AIVAN never stores passwords, cookies, session tokens, or credential material.

### Native Gateway plugin

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
| Manifest | `openclaw.plugin.json` |
| Runtime entry | `./dist/index.js` |
| Types entry | `./dist/index.d.ts` |
| Node requirement | `>=18` |
| OpenClaw package target | `^2026.6.9` |
| Plugin API compatibility | `1.0` |

Build and typecheck:

```bash
cd integrations/openclaw-aivan-plugin
npm install
npm run build
npm run typecheck
npx tsc
```

Install locally through OpenClaw:

```bash
openclaw plugins install . --force
openclaw plugins list --verbose
openclaw plugins inspect openclaw-aivan --runtime --json
```

The plugin forwards normalized events to AIVAN and preserves OpenClaw context fields such as:

```text
project_id
role_context
conversation_id
sender_id
channel
```

Context preservation is required so supplier-side replies attach to the correct trade project instead of being misclassified as new buyer inquiries.

---

## Running Tests

Python test suite:

```bash
uv run pytest
# or
uv run aivan test
```

Normal tests run in mock mode and should not require live credentials.

Core E2E scripts:

```bash
uv run python scripts/run_aivan_e2e.py
uv run python scripts/run_aivan_private_domain_rfq_e2e.py
uv run python scripts/run_aivan_marketplace_e2e.py
uv run python scripts/run_aivan_unknown_supplier_risk_e2e.py
uv run python scripts/run_aivan_platform_whitelist_e2e.py
uv run python scripts/run_gpm_llm_api_smoke.py
```

OpenClaw Gateway / ClawHub P0 checks:

```bash
python scripts/validate_clawhub_aivan_plugin.py
python scripts/run_aivan_openclaw_plugin_smoke_test.py --offline
python scripts/run_aivan_openclaw_install_smoke_test.py
python scripts/run_aivan_openclaw_gateway_p0_test.py
python scripts/run_aivan_openclaw_install_simulation.py
python scripts/run_aivan_openclaw_full_check.py
```

The full check runs the package validator, install smoke test, Gateway P0 test, and install simulation in sequence. It should exit with code `0` before any release claim.

---

## CLI Reference

| Command | Description |
|---|---|
| `uv run aivan init` | Initialize local database and platform whitelist. |
| `uv run aivan serve` | Start the local web UI and API server. |
| `uv run aivan demo` | Run the core RFQ E2E demo. |
| `uv run aivan demo-marketplace` | Run the marketplace sourcing demo. |
| `uv run aivan demo-risk-check` | Run supplier risk-screening demo. |
| `uv run aivan test` | Run the pytest suite. |
| `uv run aivan import-suppliers [file]` | Import suppliers from CSV. |
| `uv run aivan import-marketplace-results [file]` | Import marketplace result data from CSV. |
| `uv run aivan risk-check --supplier-name "Supplier Name"` | Run risk screening for a supplier. |
| `uv run aivan platforms list` | List all platform records. |
| `uv run aivan platforms whitelist` | List trusted platforms. |
| `uv run aivan platforms suggest --domain example.com --reason "Reason"` | Create a platform suggestion for review. |
| `uv run aivan accounts list` | List OpenClaw account connections recorded in AIVAN. |
| `uv run aivan accounts register --file account.json` | Register account metadata. |
| `uv run aivan accounts revoke <account_connection_id>` | Revoke account metadata. |

---

## API Reference

Default base URL:

```text
http://127.0.0.1:8765
```

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health`, `/api/health`, `/healthz` | Health checks. |
| `GET` | `/app`, `/` | Web UI. |
| `POST` | `/invoke` | OpenClaw / WeChat skill invocation endpoint. |
| `POST` | `/api/openclaw/events` | Native OpenClaw event ingestion. |
| `POST` | `/api/skill/invoke` | Skill invocation alias. |
| `POST` | `/api/rfq/create-from-event` | Create RFQ from normalized event. |
| `GET` | `/api/projects` | List trade projects. |
| `GET` | `/api/projects/{project_id}` | Fetch project detail. |
| `GET` | `/api/projects/{project_id}/events` | List project audit events. |
| `GET` | `/api/projects/{project_id}/drafts` | List project drafts. |
| `POST` | `/api/projects/{project_id}/strategy` | Update RFQ strategy. |
| `POST` | `/api/projects/{project_id}/run-gltg` | Run GLTG lead-time simulation. |
| `GET` | `/api/drafts` | List pending drafts. |
| `GET` | `/api/openclaw/drafts/{draft_id}` | Fetch draft detail. |
| `POST` | `/api/openclaw/drafts/{draft_id}/approve` | Approve and send if policy allows. |
| `POST` | `/api/openclaw/drafts/{draft_id}/reject` | Reject a pending draft. |
| `GET` | `/api/suppliers` | List active suppliers. |
| `POST` | `/api/suppliers/import` | Import suppliers by CSV body. |
| `POST` | `/api/suppliers/match` | Match suppliers for a requirement. |
| `GET` | `/api/platforms` | List known platforms. |
| `GET` | `/api/platforms/whitelist` | List trusted platforms. |
| `GET` | `/api/platforms/suggestions` | List platform suggestions. |
| `POST` | `/api/platforms/suggestions/{id}/approve` | Approve platform suggestion. |
| `GET` | `/api/openclaw/accounts` | List OpenClaw account metadata. |
| `POST` | `/api/openclaw/accounts/register` | Register OpenClaw account metadata. |
| `POST` | `/api/openclaw/accounts/{id}/revoke` | Revoke OpenClaw account metadata. |
| `GET` | `/api/user-preferences` | List user preference memory. |
| `POST` | `/api/user-preferences/update` | Upsert user preference memory. |
| `*` | `/api/gpm/*` | GPM router for AIVAN private-domain packets/context. |

When `AIVAN_API_KEY` is configured, protected endpoints require:

```http
X-AIVAN-API-Key: <configured-key>
```

---

## Giraffe DB / GPM Contract

AIVAN treats Giraffe DB / GPM as the private-domain business context source. The LLM may reason over AIVAN-supplied context, but it must not invent private supplier facts, customer history, historical prices, lead-time history, or user preference memory.

GPM outputs should preserve:

```text
source traces
lineage
missing_inputs
fallback mode
approval requirement
```

If supplier count is fewer than three, AIVAN must not crash or fabricate additional suppliers. It should surface the shortfall and continue with a guarded fallback where possible.

---

## GLTG Contract

GLTG is the authoritative lead-time simulation service. AIVAN calls it over HTTP and stores the result trace in the project audit trail.

Configure:

```env
GLTG_API_BASE_URL=http://localhost:8090
GLTG_API_TIMEOUT_SECONDS=30
```

AIVAN may explain GLTG output, but it must not replace GLTG calculations with LLM output or local invented estimates.

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

AIVAN is a decision-support and workflow-execution tool. It does not make final legal, credit, sanctions, trade-compliance, or binding commercial decisions. Users are responsible for verifying supplier information and complying with applicable laws, platform rules, and contractual obligations.

---

## License

MIT License

Copyright (c) 2025 Giraffe Technology
