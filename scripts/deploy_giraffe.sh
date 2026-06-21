#!/usr/bin/env bash
# deploy_giraffe.sh – Deploy AIVAN to the Giraffe self-hosted staging server.
#
# Required env vars (inject from CI secrets – NEVER hard-code):
#   GIRAFFE_DEPLOY_HOST   – SSH hostname / IP
#   GIRAFFE_DEPLOY_USER   – SSH user
#   GIRAFFE_SSH_KEY       – Private key content (write to temp file)
#   GIRAFFE_DEPLOY_DIR    – Remote directory, e.g. /srv/aivan
#   GIRAFFE_BRANCH        – Branch to deploy (default: main)
#   AIVAN_REMOTE_BASE_URL – Base URL of the staging instance for smoke test
set -euo pipefail

: "${GIRAFFE_DEPLOY_HOST:?GIRAFFE_DEPLOY_HOST is required}"
: "${GIRAFFE_DEPLOY_USER:?GIRAFFE_DEPLOY_USER is required}"
: "${GIRAFFE_SSH_KEY:?GIRAFFE_SSH_KEY is required}"
: "${GIRAFFE_DEPLOY_DIR:?GIRAFFE_DEPLOY_DIR is required}"
BRANCH="${GIRAFFE_BRANCH:-main}"

echo "==> Preparing SSH key..."
SSH_KEY_FILE=$(mktemp /tmp/giraffe_deploy_XXXXXX)
chmod 600 "$SSH_KEY_FILE"
printf '%s' "$GIRAFFE_SSH_KEY" > "$SSH_KEY_FILE"
trap 'rm -f "$SSH_KEY_FILE"' EXIT

SSH="ssh -i $SSH_KEY_FILE -o StrictHostKeyChecking=no -o BatchMode=yes"
REMOTE="${GIRAFFE_DEPLOY_USER}@${GIRAFFE_DEPLOY_HOST}"

echo "==> Deploying branch '$BRANCH' to $REMOTE:$GIRAFFE_DEPLOY_DIR ..."
$SSH "$REMOTE" bash -s << REMOTE_SCRIPT
set -euo pipefail
cd "${GIRAFFE_DEPLOY_DIR}"
git fetch origin
git checkout "${BRANCH}"
git pull origin "${BRANCH}"
uv sync --frozen

# Restart the service (assumes systemd unit 'aivan')
if systemctl is-active --quiet aivan 2>/dev/null; then
    systemctl restart aivan
    sleep 3
    systemctl is-active --quiet aivan || { echo 'ERROR: aivan failed to restart'; exit 1; }
fi
echo 'Deploy complete.'
REMOTE_SCRIPT

echo "==> Running remote smoke test..."
if [ -n "${AIVAN_REMOTE_BASE_URL:-}" ]; then
    # Health check
    STATUS=$(curl -sf "${AIVAN_REMOTE_BASE_URL}/api/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "error")
    if [ "$STATUS" != "ok" ]; then
        echo "ERROR: health check returned '$STATUS'"
        exit 1
    fi
    echo "Health check: $STATUS"

    # Run remote smoke script if present
    if [ -f scripts/remote_smoke.py ]; then
        AIVAN_REMOTE_BASE_URL="${AIVAN_REMOTE_BASE_URL}" \
        uv run python scripts/remote_smoke.py
    fi
else
    echo "AIVAN_REMOTE_BASE_URL not set; skipping remote smoke test."
fi

echo "==> Deployment complete."
