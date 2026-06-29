# RFQ Intake Structured DB Test Report

## 1. Schema/model changes

Added temporary DB-side intake entities:

- `InquirySheet` -> `inquiry_sheets`
- `InquiryMessage` -> `inquiry_messages`

These are business-level RFQ workspaces/messages. No physical SQL table is created per RFQ.

## 2. Structuring logic

Added deterministic parser in `src/aivan/intake/rfq_structuring.py`.

It strips parse-only trace/test prefixes such as `AIVANPR18OK`, `AIVAN-TRACE-*`, `AIVAN-OLLAMA-*`, `AIVAN-OLLAMA-NATIVE`, and `INTAKE-1`, while storing the original raw text unchanged.

Extracted fields include product name/category, quantity/unit, destination, lead time, delivery deadline, quality level, material, color, size, notes, and language.

## 3. Same-inquiry matching rule

Added conservative matcher in `src/aivan/intake/inquiry_matcher.py`.

Active sheets from the last 72 hours are scored on:

- same conversation or sender
- same product/product category
- same or compatible quantity
- same destination
- same lead time or deadline
- same quality level

Only score `>= 0.85` appends to an existing sheet as `same_existing`.

## 4. Conservative uncertain handling rule

If the message lacks enough product/quantity/destination/timing identity, it creates a new `temporary_unconfirmed` sheet with `match_decision = uncertain_new`.

Uncertain messages are never merged into existing sheets.

## 5. Tests run

Completed locally before PR publication:

```text
pytest tests/test_rfq_intake_structuring.py -q
3 passed

pytest tests/test_rfq_intake_matching.py -q
3 passed

pytest tests/test_openclaw_intake_persistence.py -q
critical downstream-failure persistence case passed

pytest --tb=short -q
431 passed, 2 skipped

python -m compileall src/aivan scripts tests -q
pass
```

This PR includes `scripts/inspect_inquiry_intake.py` for DB verification instead of adding a debug API endpoint, to avoid touching unrelated current `main.py` OpenClaw route work.

## 6. Server WeChat test messages

Operator/mobile WeChat test messages to send on server `113.249.119.30`:

```text
INTAKE-1 询价5000件格子衬衫，45天交东京，高品质
INTAKE-2 格子衬衫5000件，45天东京，高品质
INTAKE-3 询价1000件纯棉T恤，交加拿大
INTAKE-4 这个也帮我问一下
```

Status: pending external mobile WeChat/operator execution.

## 7. DB rows created

Local proof run against a temporary SQLite DB created:

- 3 `inquiry_sheets` rows
- 4 `inquiry_messages` rows

## 8. Sheet ids for each message

Local proof run:

```text
INTAKE-1 -> isheet_3cf2fa77ce4346ad, new_temporary, confidence=0.4
INTAKE-2 -> isheet_3cf2fa77ce4346ad, same_existing, confidence=1.0
INTAKE-3 -> isheet_06cf8d2638d4440b, new_temporary, confidence=0.0
INTAKE-4 -> isheet_e3d627b431184142, uncertain_new, confidence=0.55
```

## 9. Proof that INTAKE-1 and INTAKE-2 share a sheet

Local proof:

```text
SHEET isheet_3cf2fa77ce4346ad active 2 格子衬衫 东京
```

Both INTAKE-1 and INTAKE-2 use `sheet_id = isheet_3cf2fa77ce4346ad`.

## 10. Proof that INTAKE-3 has a separate sheet

Local proof:

```text
SHEET isheet_06cf8d2638d4440b active 1 纯棉t恤 加拿大
```

INTAKE-3 uses `sheet_id = isheet_06cf8d2638d4440b`.

## 11. Proof that INTAKE-4 created temporary_unconfirmed sheet

Local proof:

```text
SHEET isheet_e3d627b431184142 temporary_unconfirmed 1 None None
```

INTAKE-4 uses `match_decision = uncertain_new`.

## 12. Downstream failure persistence result

`tests/test_openclaw_intake_persistence.py` forces downstream requirement structuring to raise after the OpenClaw event is received.

Result:

- API returns degraded `status = error`
- `inquiry_sheets` count increments
- `inquiry_messages` count increments
- raw text is stored unchanged
- `structured_json.quantity = 5000`

RFQ INTAKE DB STRUCTURING: PASS
