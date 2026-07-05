# myaivan-web Branch Policy

Status: ACTIVE product decision (2026-07-05).

## Rules

1. **`myaivan-web` is a long-lived standalone product branch** for the
   myaivan.com Web UI (welcome page, conversation workspace, case/draft/audit
   API, i18n, web auth). It is deployed to the web server as a whole:

   ```bash
   git clone -b myaivan-web https://github.com/GiraffeTechnology/aivan.git
   ```

2. **Never merge `myaivan-web` into `main`.** PR #35 was intentionally closed
   unmerged. `main` must stay free of myaivan Web UI code.

3. **`main` stays stable** for AIVAN core and the OpenClaw skill/plugin
   (`integrations/openclaw-aivan-plugin/`, `skills/aivan-trade-salesperson/`).

4. **All myaivan.com Web UI work happens on `myaivan-web`** or on child
   branches whose PRs target `myaivan-web` (never `main`).

5. **Sync direction is one-way: `main` → `myaivan-web`.** When `main` gains
   fixes to shared layers (API, DB, integrations), merge `main` into
   `myaivan-web`. Never the reverse.

## Public-deployment gate

Before myaivan.com is exposed publicly, production fail-closed auth MUST be
active (implemented in `aivan.web.auth`, tests in `tests/test_myaivan_auth.py`):

- `AIVAN_ENV=production` **and** `AIVAN_API_KEY` or `AIVAN_AUTH_SECRET` set.
  Production without a secret fails closed (503) on every myaivan page and
  `/api/myaivan/*` endpoint.
- Browsers sign in at `/myaivan/login` (HMAC session cookie); API clients use
  `X-AIVAN-API-Key` / Bearer. Only `/api/myaivan/i18n/{lang}` (UI strings,
  no user/case data) is public.
- Terminate TLS at the reverse proxy in front of `uvicorn`.

## myaivan scope on this branch

- Pages: `/myaivan`, `/myaivan/work`, `/myaivan/login`
- API: `/api/myaivan/*`
- Modules: `src/aivan/web/`, `src/aivan/db/models/web_case.py`,
  myaivan templates and static assets under `src/aivan/app/`
- Tests: `tests/test_myaivan_*.py`
