# myaivan-web Branch Policy

Status: ACTIVE product decision (2026-07-05).

## Rules

1. **`myaivan-web` is the permanent standalone product branch** for the
   myaivan.com / myaivan.cn responsive workbench, session UI, role projection,
   case/audit views, i18n and Giraffe VI assets. It is deployed to the AIVAN
   server as a whole:

   ```bash
   git clone -b myaivan-web https://github.com/GiraffeTechnology/aivan.git
   ```

2. **Never merge `myaivan-web` into `main`.** PR #35 was intentionally closed
   unmerged. `main` must stay free of myaivan Web UI code.

3. **`main` stays stable** for AIVAN core and the OpenClaw skill/plugin
   (`integrations/openclaw-aivan-plugin/`, `skills/aivan-trade-salesperson/`).

4. **All myaivan.com Web UI work happens on `myaivan-web`** or on child
   branches whose PRs target `myaivan-web` (never `main`).

5. **Sync direction is one-way: `main` → `myaivan-web`.** Shared AIVAN fixes
   may be merged into this branch, including unrelated-history reconciliation
   when required. Never merge or cherry-pick this branch back into `main`.

## Public-deployment gate

Before myaivan.com or myaivan.cn is exposed publicly, production fail-closed
auth MUST be active (implemented in `aivan.api.session_auth`, tested in
`tests/test_myaivan_workbench.py`):

- `AIVAN_ENV=production` **and** `AIVAN_API_KEY` or `AIVAN_AUTH_SECRET` set.
  Production without a secret fails closed (503) on every myaivan page and
  every protected API endpoint.
- Browsers sign in at `/app` by exchanging the deployment credential for a
  signed HttpOnly session; API clients use `X-AIVAN-API-Key` / Bearer.
- The optional dedicated test account uses a separate synthetic-data tenant,
  a server-minted short-lived single-use ticket, a shorter fixed-role session,
  and server-side route restrictions that prohibit production writes and all
  outbound actions.
- Terminate TLS at the reverse proxy in front of `uvicorn`.

## myaivan scope on this branch

- Pages: `/app`, `/`
- API: `/api/session/*`, `/api/workbench/*`, and the controlled shared AIVAN
  routes rendered by the workbench
- Modules: `src/aivan/api/session_*`, `src/aivan/api/workbench_routes.py`, and
  templates/static assets under `src/aivan/app/`
- Tests: `tests/test_myaivan_workbench.py`
