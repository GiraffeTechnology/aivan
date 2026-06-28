#!/usr/bin/env bash
# Start (or verify) the AIVAN stack on the deployment server.
#
# Idempotent: a service already listening on its port is left running.
# Brings up, in order: AIVAN API, and optionally GLTG. Ollama / OpenClaw Gateway
# are expected to be managed externally but are health-probed and reported.
set -euo pipefail

# ── Configuration (override via environment) ──────────────────────────────────
export AIVAN_HOST="${AIVAN_HOST:-127.0.0.1}"
export AIVAN_PORT="${AIVAN_PORT:-8765}"
export AIVAN_MODEL_PROVIDER="${AIVAN_MODEL_PROVIDER:-ollama}"
export AIVAN_MODEL_NAME="${AIVAN_MODEL_NAME:-qwen3.5:0.8b}"
export AIVAN_MODEL_BASE_URL="${AIVAN_MODEL_BASE_URL:-http://127.0.0.1:11434/v1}"
export GIRAFFE_DB_URL="${GIRAFFE_DB_URL:-sqlite:////opt/giraffe/giraffe-db/snapshots/sqlite/aivan_synthetic_private_v1.sqlite}"
export GLTG_BASE_URL="${GLTG_BASE_URL:-http://127.0.0.1:8766}"
export GLTG_API_BASE_URL="${GLTG_API_BASE_URL:-$GLTG_BASE_URL}"

OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:18789}"
START_GLTG="${START_GLTG:-0}"   # set to 1 to start a local GLTG service
LOG_DIR="${LOG_DIR:-/tmp}"

cd "$(dirname "$0")/.."

port_listening() { # $1 = port
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&-; return 0; } || return 1
}

probe() { # $1 = label, $2 = url
  if curl -fsS --max-time 3 "$2" >/dev/null 2>&1; then
    echo "  [ok]   $1 ($2)"
  else
    echo "  [warn] $1 not reachable ($2)"
  fi
}

echo "== AIVAN stack =="
echo "AIVAN     -> ${AIVAN_HOST}:${AIVAN_PORT}"
echo "Provider  -> ${AIVAN_MODEL_PROVIDER} ${AIVAN_MODEL_NAME} (${AIVAN_MODEL_BASE_URL})"
echo "DB        -> ${GIRAFFE_DB_URL}"
echo "GLTG      -> ${GLTG_BASE_URL} (start=${START_GLTG})"
echo

echo "== Dependencies =="
probe "Ollama / Qwen"      "${OLLAMA_URL}/api/tags"
probe "OpenClaw Gateway"   "${GATEWAY_URL}/health"

# ── GLTG (optional) ───────────────────────────────────────────────────────────
if [ "$START_GLTG" = "1" ]; then
  if port_listening 8766; then
    echo "  [ok]   GLTG already listening on 8766"
  else
    echo "  [..]   starting GLTG on 8766"
    nohup uv run uvicorn aivan.integrations.gltg:app --host 127.0.0.1 --port 8766 \
      >"${LOG_DIR}/gltg.log" 2>&1 &
    sleep 2
  fi
else
  probe "GLTG" "${GLTG_BASE_URL}/health"
fi

# ── AIVAN ─────────────────────────────────────────────────────────────────────
echo
echo "== AIVAN =="
if port_listening "${AIVAN_PORT}"; then
  echo "  [ok]   AIVAN already listening on ${AIVAN_PORT}"
else
  echo "  [..]   starting AIVAN (aivan.api.main:app) on ${AIVAN_PORT}"
  nohup uv run aivan serve >"${LOG_DIR}/aivan.log" 2>&1 &
  for _ in $(seq 1 15); do
    sleep 1
    port_listening "${AIVAN_PORT}" && break
  done
fi
probe "AIVAN /health" "http://${AIVAN_HOST}:${AIVAN_PORT}/health"

echo
echo "== Smoke: AIVAN /invoke =="
curl -fsS -X POST "http://${AIVAN_HOST}:${AIVAN_PORT}/invoke" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"stack-smoke","user_input":"帮我询价 1000件格子纯棉衬衫，45天内交东京","context":{"channel":"wechat","dry_run":true}}' \
  || echo "  [warn] /invoke smoke failed"
echo
echo "Done."
