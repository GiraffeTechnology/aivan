# AIVAN OpenClaw / WeChat Invocation Audit — 2026-06-28

Scope: `GiraffeTechnology/aivan` only. Goal: make AIVAN invocable from the real
WeChat mobile client via OpenClaw (P0). Defects below were found and fixed
in-place on branch `claude/wechat-mobile-avian-kwv3np`.

---

### DEFECT-INVOKE-01
**Location:** `src/aivan/api/main.py` (route table)
**Severity:** BLOCKER
**Description:** No `POST /invoke` endpoint existed. The OpenClaw skill contract,
the audit smoke test, and the WeChat E2E task all target `POST /invoke` with
`{session_id, user_input, context}` → `{status, output, artifacts}`. Only the
heavy `/api/openclaw/events` and `/api/skill/invoke` routes existed.
**Root cause:** The skill-invocation endpoint was never implemented; integration
relied solely on the event-forwarding route.
**Fix applied:** Added `POST /invoke` (`src/aivan/api/main.py`) backed by
`src/aivan/api/invoke.py`. Unauthenticated so OpenClaw's registration probe and
the WeChat path can reach it. Always returns `{status, output, artifacts,
trace_id}` and never raises.

### DEFECT-BRIDGE-500-02
**Location:** `src/aivan/api/main.py` `openclaw_event` (old `except: raise HTTPException(500)`)
**Severity:** BLOCKER
**Description:** When the RFQ pipeline raised (e.g. `GLTGUnavailableError`,
giraffe-db down, LLM timeout), `/api/openclaw/events` returned HTTP 500. OpenClaw
renders a non-JSON / 500 skill response as the generic
"Agent couldn't generate a response. Please try again." in WeChat.
**Root cause:** Pipeline dependency failures were converted to 500 instead of a
structured degraded reply.
**Fix applied (P0-1, P0-2):** `_handle_openclaw_event` now catches every
exception, rolls back, and returns HTTP 200 with `status:"error"` plus a
human-readable `reply_text` built from deterministic intent extraction. Success
responses also carry `reply_text` (= `user_control_message`/`message`).

### DEFECT-BRIDGE-SWALLOW-03
**Location:** `integrations/openclaw-aivan-plugin/index.ts` `runAttempt`
**Severity:** HIGH
**Description:** On any AIVAN failure the harness returned
`buildPassThroughResult` (empty `assistantTexts`), so WeChat showed the generic
failure with no diagnostic, and the error was only on stderr.
**Root cause:** Errors were swallowed into an empty pass-through.
**Fix applied (P0-3):** The harness now calls the robust `/invoke`, logs the
AIVAN error, and returns a **visible diagnostic** (`buildSuccessResult` with the
error text) instead of an empty pass-through. Connection failures and structured
errors both surface a meaningful WeChat message.

### DEFECT-PAYLOAD-SHAPE-04
**Location:** `src/aivan/api/invoke.py` `normalize_invoke_payload`
**Severity:** HIGH
**Description:** Different OpenClaw/WeChat adapters carry the message under
different keys (`user_input`, `message`, `text`, `content`, `input`, nested
`payload.text`, `event.message.text`, `body.content`). A strict model would 422
on the unexpected shape.
**Root cause:** No payload normalizer.
**Fix applied (Phase 5):** `extract_message_text` accepts all common shapes;
missing text returns a structured error reply rather than a validation error.

### DEFECT-INTENT-CJK-05
**Location:** `src/aivan/api/invoke.py` `extract_rfq_intent`
**Severity:** MEDIUM
**Description:** Quantity/product were not extracted from Chinese RFQs like
`1000件格子纯棉衬衫` because a trailing `\b` after the unit char never matches
(Chinese chars are word characters in Python regex, so there is no boundary
between `件` and `格`).
**Root cause:** ASCII-centric word-boundary assumption.
**Fix applied:** Removed the `\b`; deterministic extraction now yields
`product=格子纯棉衬衫, quantity=1000, delivery_time=45天内, destination=东京,
intent=supplier_quotation` with no LLM/DB dependency.

### DEFECT-NO-GLOBAL-HANDLER-06
**Location:** `src/aivan/api/main.py`
**Severity:** MEDIUM
**Description:** Unhandled exceptions on any route produced a plaintext traceback
/ HTML 500, which OpenClaw can misread as a connection failure.
**Fix applied (Phase 6):** Added a global FastAPI exception handler returning
`{status:"error", output, artifacts:[]}` as JSON. HTTPException (auth 401/403)
keeps its existing JSON behavior.

### DEFECT-MANIFEST-07
**Location:** repo root
**Severity:** MEDIUM
**Description:** No machine-readable skill manifest declaring the invocation
endpoint/schema.
**Fix applied:** Added `skill.json` (`method:POST`, `endpoint:/invoke`, request +
response schemas, `health:/health`). `tests/test_manifest_route.py` asserts the
declared endpoint exists in the live FastAPI route table.

---

## Cross-repo findings (documented only — NOT modified, per scope lock)

- **GLTG service availability** (`GiraffeTechnology/GLTG`): if the standalone
  GLTG service on `127.0.0.1:8766` is not running, `GLTGClient.simulate` raises
  `GLTGUnavailableError`. AIVAN now degrades gracefully, but full supplier/lead
  -time enrichment requires GLTG to be started (`START_GLTG=1
  scripts/start_server_stack.sh`).
- **giraffe-db snapshot** (`GiraffeTechnology/giraffe-db`): full DB-backed
  supplier results require the SQLite snapshot / Postgres URL via
  `GIRAFFE_DB_URL`. Absent it, AIVAN returns the structured degraded reply rather
  than hallucinating suppliers.
- **OpenClaw pairing/scope** (`GiraffeTechnology/openclaw`): WeChat invocation
  additionally requires the device pairing to be approved with the WeChat scope.
  This is an operator action — see `scripts/openclaw_pairing_check.sh`. It is the
  only remaining potential manual blocker and cannot be resolved from the aivan
  repo.

---

## Summary

- Defects found: 7 (3 BLOCKER, 2 HIGH, 2 MEDIUM) + 3 cross-repo findings.
- Defects fixed in `aivan`: 7 / 7.
- Tests: `tests/test_openclaw_smoke.py`, `tests/test_wechat_procurement_message.py`,
  `tests/test_manifest_route.py` added; full suite **414 passed, 2 skipped**.
  Plugin gateway harness **37/37** with the real OpenClaw SDK.
- Remaining manual action: OpenClaw WeChat pairing/scope approval (cross-repo).
