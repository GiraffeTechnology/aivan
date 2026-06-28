# DEFECTS — WeChat → OpenClaw → AIVAN HTTP 500 (2026-06-29)

Scope: `GiraffeTechnology/aivan` only. Cross-repo findings are documented, not modified.

## Environment constraint

This investigation was done at the code level. The production server
`113.249.119.30` (STEP 1 live traceback, STEP 6 live WeChat round-trip) was not
reachable from the analysis environment, so the live traceback and the live
WeChat trigger were not captured. The root cause was instead established from the
invocation code path and the OpenClaw bridge contract, and the fix is verified by
the test suite.

## Call chain (verified from source)

WeChat → OpenClaw → **bridge plugin** → AIVAN HTTP.

`integrations/openclaw-aivan-plugin/index.ts` is the bridge. In `runAttempt`
(`index.ts:418`) it normalises the inbound message into an **OpenClaw-standard
event** (`extractPrompt` / `extractSessionContext`) and POSTs it to AIVAN via
`forwardEvent` → `POST /api/openclaw/events` (`index.ts:123`). The skill-facing
AIVAN endpoints are:

- `POST /api/openclaw/events` (`src/aivan/api/main.py`)
- `POST /api/skill/invoke` (`src/aivan/api/main.py`)
- `POST /api/rfq/create-from-event` (`src/aivan/api/main.py`)

All three call `parse_openclaw_event` → `create_rfq_from_event`.

---

## DEFECT-W04 — Skill-invocation endpoints surface raw HTTP 500 (ROOT CAUSE CLASS)

**Location:** `src/aivan/api/main.py` — `/api/skill/invoke`, `/api/openclaw/events`,
`/api/rfq/create-from-event`; no app-level exception handler existed.
**Severity:** BLOCKER
**Description:** `/api/skill/invoke` had no error handling at all, so any exception
in `parse_openclaw_event` / `create_rfq_from_event` propagated as a raw HTTP 500.
`/api/openclaw/events` and `/api/rfq/create-from-event` caught exceptions only to
re-raise them as `HTTPException(status_code=500, detail=str(e))`. There was no
global exception handler.
**Root cause:** `create_rfq_from_event` fans out to environment-dependent
integrations — the LLM gateway, `GiraffeDBClient.build_context`, and
`GLTGClient.simulate`. When any of these is unavailable or misconfigured on the
server, the exception becomes an HTTP 500. OpenClaw treats a 500 from a skill as
"skill broken" and disables it; only `{"status":"error"}` over HTTP 200 is a
recoverable "skill returned error" the user can see and retry. This is exactly
the contract STEP 4 mandates.
**Fix applied:**
- Registered a global `@app.exception_handler(Exception)` that logs the traceback
  and returns HTTP 200 with `{"status":"error","output":...}`. Explicit
  `HTTPException` (401/403/404/409) still flows through FastAPI's own handler and
  keeps its status code (verified by `test_auth_error_keeps_its_status_code`).
- The three skill endpoints now return a uniform envelope via `_skill_response`:
  `{"status":"ok","output":<message>, **result}`. Existing top-level fields
  (`project_id`, `action`, `strategy`, `gltg_simulation`, ...) are preserved, so
  the bridge plugin and existing API tests keep working. The local
  `except → HTTPException(500)` wrappers were removed; error handling is now
  centralized in the global handler.

---

## DEFECT-W01 / W02 — Pydantic schema mismatch → ValidationError → 500 — NOT PRESENT

**Location:** `src/aivan/openclaw/event_adapter.py:4`, `src/aivan/openclaw/contracts.py:3`
**Severity:** N/A (not a defect)
**Description / proof:** `parse_openclaw_event` constructs `OpenClawEvent` field by
field using `data.get(<field>, <default>)` for every field, including the only
required field, `conversation_id` (`get("conversation_id", "")`). A payload with
unknown extra keys is ignored; a payload missing keys gets defaults. No inbound
shape can raise a `ValidationError` here, so the W01/W02 schema-mismatch 500 path
does not exist. In addition, the documented WeChat raw shape
(`{from_user, content, room_id, ...}`) does not reach AIVAN directly: the bridge
plugin (`index.ts`) already normalises WeChat into the OpenClaw-standard shape
before calling AIVAN.
**Decision:** No production WeChat→OpenClaw normalization layer was added inside
AIVAN. Adding one would be speculative compatibility for input that the bridge
never sends, which the repo architecture guidance discourages. If a future direct
caller ever sends the raw WeChat shape, it is now handled safely (no 500) by
DEFECT-W04's envelope rather than producing a meaningful reply — revisit only with
a real captured payload.

---

## DEFECT-W03 — HMAC Bearer auth missing on webhook chain — NOT APPLICABLE AS DESCRIBED

**Location:** `src/aivan/api/main.py:20` (`_require_api_key`), `integrations/openclaw-aivan-plugin/index.ts:32`
**Severity:** Informational
**Description / proof:** AIVAN has no HMAC / `Authorization: Bearer` middleware.
Auth is an optional shared secret header, `X-AIVAN-API-Key`, enforced by
`_require_api_key` only when the `AIVAN_API_KEY` env var is set. The bridge plugin
forwards that same key from its own `AIVAN_API_KEY` env (`index.ts:buildHeaders`).
`/api/skill/invoke` is intentionally unauthenticated (it already is the
"public invoke" route from STEP 5 option C). A key mismatch yields HTTP **401/403**,
not 500, so this is not the 500 root cause.
**Recommendation (no code change):** If the server sets `AIVAN_API_KEY`, ensure the
OpenClaw bridge process has the same `AIVAN_API_KEY` so `/api/openclaw/events`
authenticates; otherwise route the bridge to the unauthenticated `/api/skill/invoke`.

---

## Validation

- `tests/test_wechat_webhook.py` added: WeChat-shaped event on both endpoints
  returns a valid envelope; minimal payload does not 500; an injected unhandled
  exception returns HTTP 200 + `{"status":"error"}`; an auth failure still returns 401.
- Full suite: `uv run pytest` → 406 passed, 2 skipped.
- No temporary `[DEBUG-RAW-BODY]` logging was committed (STEP 2 debug line was not
  added to the repo, per the constraint to never ship it).
