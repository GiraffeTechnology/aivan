# MyAivan Release Branch Policy

MyAivan is Aivan's web version, not a separate business system. `myaivan-web` is the existing release branch. A release branch is an engineering delivery choice, not an additional product boundary.

## Release integration

- Select the target release ref explicitly. Submit integration and policy changes as normal pull requests under the repository's current protections; a draft proposal does not enable a new policy.
- Do not silently retarget open PRs, rename branches to evade checks, rewrite history, or bypass required reviews, status checks, code ownership or unresolved-thread rules.
- Branch names and changed file paths alone do not create a permanent integration prohibition. Reviewed changes may establish a different release layout without changing product responsibilities or duplicating business state.
- Preserve existing source and release history. This document does not rename, move, merge or delete any branch, approve a deployment, or change authentication and human-approval requirements.
- Record the exact source commit and applicable check results for each authorized integration. A merged source change and a deployed, accepted release remain different outcomes.

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

