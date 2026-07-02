# AIVAN CTYUN Production Deployment (post-PR29)

Private-domain, CPU-only. Production local model: **qwen3.5:2b**. External
LLM/VLM APIs are OFF and require explicit approval.

> Do **not** restart production services until the pre-flight checks pass and a
> human approves. This document is the dry-run plan.

## 0. Pre-flight (no service impact)

```bash
# main includes the PR29 merge
cd /giraffe-workspace/aivan && git fetch origin main
git log --oneline -1 origin/main            # expect 8135db6 (PR29 merge)
git rev-parse origin/main                    # expect 8135db6b86b5ad9212182ec4bee2b426a76aaf98

# production model present, rejected model absent
ollama list | grep -E 'qwen3\.5:2b'          # MUST be present
ollama list | grep -E 'qwen3\.5:4b' && echo "REMOVE 4b" || echo "4b absent (ok)"

# tests + integrity benchmark against the real model
uv sync
uv run pytest -q
uv run python scripts/benchmark_small_model_boundary.py \
  --modes C D --progress --expected-local-model qwen3.5:2b \
  --fail-on-threshold --out artifacts/ctyun-main-qwen35-2b-postmerge
# integrity_status must be "pass" for C and D. capability (local_call_failure_rate)
# is report-only. If integrity fails -> STOP, do not deploy.

# operational smoke (safety invariants against qwen3.5:2b)
AIVAN_LLM_PROVIDER=ollama OLLAMA_MODEL=qwen3.5:2b \
  uv run python scripts/run_aivan_prod_smoke.py
```

If `qwen3.5:4b` is present: `ollama rm qwen3.5:4b`.
If `qwen3.5:2b` is missing: `ollama pull qwen3.5:2b` and re-run pre-flight.

## 1. Backup (reversible)

```bash
TS=$(date +%Y%m%d-%H%M%S)
sudo cp -a /opt/giraffe/aivan /opt/giraffe/aivan.bak-$TS
sudo cp -a /opt/giraffe/aivan/.env /opt/giraffe/aivan/.env.bak-$TS
# record current commit for rollback
cd /opt/giraffe/aivan && git rev-parse HEAD | sudo tee /opt/giraffe/aivan.bak-$TS/PREV_COMMIT
```

## 2. Pull latest main

```bash
cd /opt/giraffe/aivan
git fetch origin main
git checkout main
git reset --hard origin/main            # 8135db6...
git rev-parse HEAD                        # confirm 8135db6b86b5ad9212182ec4bee2b426a76aaf98
```

## 3. Install dependencies

```bash
cd /opt/giraffe/aivan
uv sync --frozen        # or `uv sync` if the lockfile changed
```

## 4. Apply environment

```bash
# Base the production env on the tracked template, then fill secrets.
# deploy/aivan.production.env.example -> /opt/giraffe/aivan/.env
# REQUIRED (fail-closed auth): AIVAN_API_KEY or AIVAN_AUTH_SECRET
# Confirm the model policy exactly:
grep -E '^(AIVAN_LLM_PROVIDER|OLLAMA_MODEL|AIVAN_EXTERNAL_MODEL_API_ENABLED|AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED|AIVAN_VLM_API_ENABLED|AIVAN_ENV)=' /opt/giraffe/aivan/.env
# Expected:
#   AIVAN_ENV=production
#   AIVAN_LLM_PROVIDER=ollama
#   OLLAMA_MODEL=qwen3.5:2b
#   AIVAN_EXTERNAL_MODEL_API_ENABLED=false
#   AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED=false
#   AIVAN_VLM_API_ENABLED=false
```

## 5. Migrations / checks

AIVAN uses SQLAlchemy `create_all` at startup (no Alembic migrations in this
repo). Just verify the app imports and the DB path is writable:

```bash
cd /opt/giraffe/aivan
uv run python -c "import aivan.api.main as m; print('import OK', m.app.title)"
test -w "$(dirname "${AIVAN_DB_URL##sqlite:///}")" && echo "db dir writable"
```

## 6. Restart AIVAN only (requires explicit approval)

```bash
# Restart ONLY the AIVAN service; do not touch Ollama / GLTG / language-skill.
sudo systemctl restart aivan            # (adjust to the actual unit name)
sudo systemctl status aivan --no-pager | head -20
```

## 7. Post-restart verification (fail-closed & no leaks)

```bash
# Health open, protected route fails closed without a key.
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/health          # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/api/projects     # 401/403/503

# One real RFQ end-to-end (authenticated), then inspect events:
#  - no external model API call
#  - no mock fallback (provider telemetry shows ollama/qwen3.5:2b)
#  - no outbound message before human approval (drafts stay pending_approval)
AIVAN_LLM_PROVIDER=ollama OLLAMA_MODEL=qwen3.5:2b \
  uv run python scripts/run_aivan_prod_smoke.py
```

## 8. Rollback

```bash
TS=<the backup timestamp>
sudo systemctl stop aivan
cd /opt/giraffe/aivan && git reset --hard "$(cat /opt/giraffe/aivan.bak-$TS/PREV_COMMIT)"
sudo cp -a /opt/giraffe/aivan.bak-$TS/.env /opt/giraffe/aivan/.env
uv sync --frozen
sudo systemctl start aivan
```

## Go / no-go

Deploy only if ALL hold:
- `origin/main` == `8135db6b86b5ad9212182ec4bee2b426a76aaf98`
- `ollama list` has `qwen3.5:2b`, no `qwen3.5:4b`
- `uv run pytest -q` green
- benchmark C & D `integrity_status=pass` (capability report-only)
- prod smoke: all safety checks pass, 401/403/503 on protected routes
