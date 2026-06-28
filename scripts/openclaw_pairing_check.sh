#!/usr/bin/env bash
# Inspect OpenClaw pairing state for the WeChat device and surface the exact
# approval command. Never auto-approves unless explicitly opted in.
#
#   OPENCLAW_APPROVE_PAIRING=1  approve pending WeChat pairing requests
#
# Without that flag this script only reports state and prints the manual command.
set -euo pipefail

OPENCLAW="${OPENCLAW_BIN:-openclaw}"
PLATFORM="${OPENCLAW_PAIRING_PLATFORM:-weixin}"

if ! command -v "$OPENCLAW" >/dev/null 2>&1; then
  echo "[error] '$OPENCLAW' not found on PATH. Set OPENCLAW_BIN." >&2
  exit 1
fi

echo "== OpenClaw state =="
"$OPENCLAW" gateway status || true
echo
echo "== Pairing requests =="
"$OPENCLAW" pairing list || true

# Extract pending request ids (best-effort; tolerant of CLI format drift).
PENDING="$("$OPENCLAW" pairing list 2>/dev/null | grep -iE "pending|pairing|${PLATFORM}" || true)"

if [ -z "$PENDING" ]; then
  echo
  echo "No pending ${PLATFORM} pairing requests detected."
  exit 0
fi

echo
echo "Pending pairing detected:"
echo "$PENDING"

REQUEST_ID="$(printf '%s\n' "$PENDING" | grep -oE '[0-9a-fA-F-]{8,}' | head -n1 || true)"

if [ -z "$REQUEST_ID" ]; then
  echo "[warn] Could not parse a request id automatically. Inspect 'pairing list' output above."
  exit 0
fi

echo "Request id: ${REQUEST_ID}"

if [ "${OPENCLAW_APPROVE_PAIRING:-0}" = "1" ]; then
  echo "[action] approving (OPENCLAW_APPROVE_PAIRING=1)"
  "$OPENCLAW" pairing approve "${PLATFORM}" "${REQUEST_ID}"
else
  echo
  echo "To approve manually (minimum required scope only):"
  echo "  ${OPENCLAW} pairing approve ${PLATFORM} ${REQUEST_ID}"
fi
