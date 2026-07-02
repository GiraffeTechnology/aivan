# AIVAN — Private-Domain AI Trade Execution Worker

`Python 3.11+` | `AIVAN v0.2.0` | `Standalone Product` | `OpenClaw Gateway` | `Multi-LLM` | `Giraffe DB / GPM` | `GLTG` | `Human-in-the-loop`

AIVAN is a private-domain AI trade execution worker built for high-stakes RFQ and quote workflows. It connects to approved private-domain communication channels through OpenClaw, receives buyer inquiries from IM, enterprise chat, email-like channels, marketplace, or other approved connectors, structures RFQ intake data, checks whether a new inquiry belongs to an existing RFQ workspace, and persists the workflow into AIVAN DB / Giraffe DB.

AIVAN owns the trade execution logic. OpenClaw owns channel and account connectivity. WeChat has been validated as a priority IM channel in the live OpenClaw → AIVAN test path, and it is especially important for Mainland China deployment because it is the dominant IM channel there.

AIVAN helps a trading company receive inquiries, structure buyer requirements, run controlled reasoning through local or configured LLM providers, call GLTG for lead-time simulation, generate quote or supplier-follow-up drafts, and keep all counterparty-facing actions behind a mandatory human approval gate.

AIVAN is not a generic chatbot. It is an auditable trade-execution system for trading companies, merchandisers, sourcing teams, and cross-border procurement operators.

---

## Current Status

Status snapshot: **2026-07-01**.

| Area | Status | Notes |
|---|---:|---|
| Local mock-mode install | PASS | No live credentials required. |
| Local AIVAN demos | PASS | RFQ, marketplace, risk, whitelist, and approval-gate flows run in mock mode. |
| AIVAN runtime / API | PASS | FastAPI app exposes `/app`, `/invoke`, `/api/openclaw/events`, RFQ, project, draft, platform, account, GPM, and health endpoints. |
| Local state DB | PASS | SQLite for local development; PostgreSQL can be used through `AIVAN_DB_URL` in server deployment. |
| OpenClaw plugin package | PASS | `@giraffetechnology/openclaw-aivan` builds and typechecks as a Gateway plugin. |
| OpenClaw → AIVAN live IM invocation | PASS | A live WeChat message reached the AIVAN/OpenClaw invocation path. |
| Local Ollama provider | PASS | Native Ollama `/api/chat` provider is available for server-local models such as `qwen3.5:0.8b`. |
| Live RFQ business-flow acceptance | IN PROGRESS | AIVAN must complete one live simple RFQ/quote workflow with local model and GLTG dependencies available. |
| ClawHub production publication | NOT READY | Requires both Gateway P0 acceptance and live business-flow acceptance. |

Required live acceptance path:

```text
IM / Email / Approved Private-Domain Channel
→ OpenClaw Gateway
→ openclaw-aivan plugin
→ AIVAN /invoke or /api/openclaw/events
→ configured local or hosted LLM provider
→ GLTG lead-time simulation
→ RFQ/project created or updated
→ inbound event and OpenClaw context stored
→ pending quote, draft, or structured approval request created
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

AIVAN focuses on private-domain trade execution:

- RFQ intake from IM, enterprise chat, email-like, marketplace, and approved private-domain channels
- validated WeChat live testing path through OpenClaw
- WeChat priority configuration for Mainland China deployment while keeping the architecture channel-neutral
- structured inquiry parsing and temporary RFQ workspace grouping
- same-inquiry detection and conservative non-merge handling
- local Ollama support for server-side testing without Qwen/DashScope API dependency
- GLTG lead-time simulation and risk metadata preservation
- optional Giraffe DB / GPM workflow memory and execution packet persistence
- supplier routing, draft generation, and quote workflow preparation
- human-in-the-loop approval before any counterparty-facing message is sent

---

## Product Boundary

AIVAN owns:

```text
RFQ/project workflow
trade event classification
RFQ intake structuring
same-inquiry grouping policy
private-domain context orchestration
Giraffe DB / GPM integration
GLTG lead-time simulation calls
supplier routing logic
supplier risk screening
user preference memory usage
draft and quote preparation
human approval workflow
audit trail generation
OpenClaw event ingestion
channel execution policy
```

OpenClaw owns:

```text
IM account connectivity
email-like connector connectivity
approved private-domain channel connectivity
channel account sessions
connector lifecycle
Gateway plugin runtime
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
11. IM and email-like channels are user-control channels.
12. Current counterparty outbound execution is approval-first and email/OpenClaw-policy controlled unless an official, API-permitted, auditable channel is implemented.
13. Never log API keys, credentials, cookies, tokens, private keys, or private server secrets.

---

## Architecture

```text
IM / Email / Marketplace / Approved Private-Domain Channel
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
                ├── RFQ intake structuring
                ├── same-inquiry workspace grouping
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

Local Ollama example:

```bash
ollama list
```

```env
AIVAN_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=<exact-model-name-from-ollama-list>
QWEN_API_KEY=
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
| `AIVAN_WEB_SEARCH_PROVIDER` | `mock` | Web-search provider. |
| `AIVAN_WEB_SEARCH_MAX_RESULTS` | `10` | Maximum results per search. |
| `AIVAN_ENABLE_UNKNOWN_SUPPLIER_RISK_SEARCH` | `true` | Run risk search for unknown suppliers. |
| `AIVAN_BLOCK_CRITICAL_RISK_SUPPLIERS` | `false` | Block critical-risk suppliers when configured. |
| `AIVAN_REQUIRE_RISK_REVIEW_FOR_UNKNOWN_SUPPLIERS` | `true` | Require review for unknown suppliers. |
| `AIVAN_DEFAULT_MARGIN_RATE` | `0.15` | Default margin applied when generating buyer quotes. |
| `AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER` | `true` | Do not expose supplier identity to buyers by default. |
| `AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER` | `true` | Do not expose supplier pricing to buyers by default. |
| `GLTG_API_BASE_URL` | `http://localhost:8090` | Standalone GLTG service base URL. |
| `GLTG_API_TIMEOUT_SECONDS` | `30` | GLTG request timeout. |

---

## Direct OpenClaw Event Test

Run a local OpenClaw-shaped event before testing a live IM connector:

```bash
curl -sS http://127.0.0.1:8765/api/openclaw/events \
  -H "Content-Type: application/json" \
  -d '{
    "source": "openclaw",
    "channel": "openclaw-weixin",
    "conversation_id": "local-test",
    "sender_id": "operator",
    "message_id": "local-rfq-001",
    "message_text": "询价5000件格子衬衫，45天交东京，高品质，请给我一个初步报价"
  }' | python -m json.tool
```

Expected behavior:

```text
AIVAN receives the event.
The configured model/provider is available.
GLTG is called for lead-time simulation.
A project/RFQ is created or updated.
A pending approval draft or quote summary is created.
No counterparty-facing message is sent without approval.
```

---

## Development Tests

```bash
uv run pytest --tb=short -q
python -m compileall src/aivan scripts tests -q
```

Focused smoke tests:

```bash
uv run pytest tests/test_ollama_provider.py -q
uv run pytest tests/test_gltg_client.py -q
uv run python scripts/validate_clawhub_aivan_plugin.py
uv run python scripts/run_aivan_openclaw_plugin_smoke_test.py --offline
```

---

## Small Local Model Boundary Benchmark

Measures the production capability boundary of the CTYUN local-only model
(`qwen3.5:0.8b`) with external provider APIs OFF. The harness reads real provider
telemetry (not env guesses): modes C/D fail unless a real Ollama call with the
expected model is recorded for every case, with zero external API calls and zero
mock fallback.

Developer ergonomics:

| Flag | Effect |
|---|---|
| `--max-cases N` | Run only the first N (post-filter) cases. |
| `--case-id ID` | Run only this case id (repeatable). |
| `--progress` | Print a live per-case line (mode, case_id, tier, start, elapsed, provider, model, tokens, PASS/FAIL). |
| `--per-case-timeout S` | Mark any case exceeding S seconds as a failed timeout and continue (unless `--fail-fast`). |
| `--fail-fast` | Stop at the first failing case. |
| `--fail-on-threshold` | Exit non-zero if any hard threshold fails. |
| `--max-local-failure-rate F` | C/D only: fail if the local-model call-failure rate exceeds F (default off). |

Incremental per-case results are always streamed to
`artifacts/benchmark_events.jsonl` so a long CTYUN run is inspectable before it
finishes. Passing no filters preserves the original full-run behavior.

### Integrity vs capability (Mode C/D)

Each case records its real provider telemetry (`configured_provider`,
`used_provider`, `model`, `ok`, `provider_error`, `fell_back_to_mock`,
`external_api_called`) and a `local_call_status`, read from the gateway — never
inferred from env:

| `local_call_status` | Meaning | Hard threshold |
|---|---|---|
| `real_local_call` | qwen3.5:0.8b called and returned OK | pass |
| `local_call_failed` | qwen3.5:0.8b called but couldn't produce valid output | **reported, not a hard fail** (measured capability; gate with `--max-local-failure-rate`) |
| `expected_local_call_missing` | model-required case never attempted a local call | **hard fail** |
| `intentionally_skipped` | fixture set `llm_required: false` (deterministic/no-model case) | pass |
| `mock_fallback` / `wrong_provider` / `unexpected_local_model` | silent substitution | **hard fail** |

Integrity hard-fails: silent mock fallback, any external API call, a
model-required case that never attempted the local model, wrong provider/model,
or Ollama never once succeeding (0 successful calls = effectively dead). A
called-but-failed 0.8b is a capability datapoint, not an integrity violation —
so a run like "21 real / 10 failed" passes integrity and reports a 32% local
failure rate for the accuracy discussion.

Smoke command (fast local check against CTYUN `qwen3.5:0.8b`):

```bash
uv run python scripts/benchmark_small_model_boundary.py --modes C --max-cases 3 --progress --fail-on-threshold
```

Full release run:

```bash
uv run python scripts/benchmark_small_model_boundary.py --modes C D --progress --fail-on-threshold
```

---

## Release / Live Acceptance Checklist

Before production publication or ClawHub release:

```text
1. Plugin build/typecheck passes.
2. OpenClaw plugin metadata validates.
3. Offline plugin smoke test passes.
4. AIVAN API health check passes.
5. Direct /api/openclaw/events test passes.
6. Configured LLM provider is available.
7. GLTG service is available.
8. Giraffe DB / GPM integration is either available or intentionally disabled for the test scope.
9. A live IM message reaches OpenClaw Gateway and AIVAN.
10. AIVAN creates or updates an RFQ/project.
11. AIVAN generates a pending approval quote or draft.
12. No counterparty outbound message is sent without human approval.
```

---

## License

See `LICENSE`.
