# AIVAN ⇄ OpenClaw / WeChat — Server Deployment

How AIVAN is invoked from the real WeChat mobile client, and how to bring the
stack up on the deployment server.

## Invocation path

```
WeChat phone
  → OpenClaw Gateway (127.0.0.1:18789)
    → openclaw-aivan plugin (AgentHarness.runAttempt)
      → POST http://127.0.0.1:8765/invoke      ← AIVAN robust skill endpoint
        → deterministic RFQ intent extraction (always)
        → full RFQ pipeline within AIVAN_INVOKE_TIMEOUT_SECONDS (best-effort)
      ← { status, output, artifacts, trace_id }
    ← assistant reply text
  ← WeChat message
```

The plugin lives in `integrations/openclaw-aivan-plugin` and registers an
OpenClaw **agent harness**. It calls AIVAN's `/invoke` endpoint, which is
designed to **never** return a non-JSON / 500 response — that is what previously
caused WeChat to show "Agent couldn't generate a response."

## Service map

| Service          | Address                | Notes                                  |
|------------------|------------------------|----------------------------------------|
| AIVAN API        | `127.0.0.1:8765`       | `aivan serve` → `aivan.api.main:app`   |
| OpenClaw Gateway | `127.0.0.1:18789`      | hosts the openclaw-aivan plugin        |
| Ollama / Qwen    | `127.0.0.1:11434`      | local LLM (optional)                   |
| GLTG             | `127.0.0.1:8766`       | optional; AIVAN degrades if absent     |

## Environment

Use the variable names AIVAN's runtime actually reads:

```bash
export AIVAN_HOST=127.0.0.1
export AIVAN_PORT=8765

# DB (aivan.db.session reads AIVAN_DB_URL):
export AIVAN_DB_URL=sqlite:////opt/giraffe/giraffe-db/snapshots/sqlite/aivan_synthetic_private_v1.sqlite

# LLM (aivan.llm.config reads AIVAN_LLM_PROVIDER; the openai_compatible provider
# reads OPENAI_*). Local Ollama exposes an OpenAI-compatible API on :11434/v1:
export AIVAN_LLM_PROVIDER=openai_compatible
export OPENAI_BASE_URL=http://127.0.0.1:11434/v1
export OPENAI_MODEL=qwen3.5:0.8b
export OPENAI_API_KEY=ollama   # non-empty placeholder; Ollama ignores it

export GLTG_API_BASE_URL=http://127.0.0.1:8766
# Optional: bound the per-invocation pipeline (seconds). Default 12.
export AIVAN_INVOKE_TIMEOUT_SECONDS=12
```

`scripts/start_server_stack.sh` also accepts the older `AIVAN_MODEL_*` /
`GIRAFFE_DB_URL` names as aliases and maps them onto the above.

The AIVAN host/port are **unified** through `AIVAN_HOST`/`AIVAN_PORT`; both the
CLI (`aivan serve`) and the plugin default (`AIVAN_BASE_URL`,
`http://127.0.0.1:8765`) agree.

## Bring up the stack

```bash
# Idempotent: does not restart services already listening.
# START_GLTG=1 also launches a local GLTG service on 8766.
START_GLTG=1 scripts/start_server_stack.sh
```

## Verify

```bash
curl http://127.0.0.1:11434/api/tags          # Ollama
curl http://127.0.0.1:8765/health             # AIVAN
curl http://127.0.0.1:18789/health            # OpenClaw Gateway

curl -sS -X POST http://127.0.0.1:8765/invoke \
  -H "Content-Type: application/json" \
  -d '{"session_id":"wechat-direct-final",
       "user_input":"帮我询价 1000件格子纯棉衬衫，45天内交东京",
       "context":{"channel":"wechat","dry_run":true}}' | jq .
```

Expected: HTTP 200, `status:"ok"`, and an `output` that names the extracted
product / quantity / delivery / destination. If GLTG or giraffe-db are down the
reply degrades to a clear acknowledgement — it never 500s and never hallucinates
suppliers.

## Pairing / scope (operator action)

Real WeChat invocation also requires the WeChat device pairing to be approved
with the right scope in OpenClaw. This is the only step that lives outside the
aivan repo:

```bash
# Reports pending pairings + the exact manual approval command.
scripts/openclaw_pairing_check.sh
# Approve explicitly (does not auto-approve all scopes):
OPENCLAW_APPROVE_PAIRING=1 scripts/openclaw_pairing_check.sh
```

## Rebuilding the plugin

The harness ships as `integrations/openclaw-aivan-plugin/dist/index.js`. After
editing `index.ts`:

```bash
cd integrations/openclaw-aivan-plugin
npm install
npm run build               # tsc → dist/
node test-gateway-harness.mjs   # gateway integration test
```
