# G2-A security remediation RED evidence

- Date: 2026-08-28 (Asia/Shanghai)
- Baseline commit: `1cc6f211f428e8c00fa1639ba1084cff833db630`
- Baseline tree: `79bd5e529fa9c5599657f81f874710725df88464`
- Remote PR #76 head with identical tree: `535d165dcc6f782411c76630c4ad8f54e683e97c`
- Command: `python -m pytest tests/unit/gpm/test_g2a_contract.py -q`
- Runtime: `C:\Users\Administrator\Documents\aivan\repo\.venv\Scripts\python.exe`
- Result before implementation changes: **17 failed, 21 passed, 1 warning**

The failures reproduced all four audit blockers:

1. A tenant-only HMAC plus caller-supplied actor/role headers approved a packet (`200`, expected `403`).
2. Versioned provider `404`/`409` decision errors were returned as `GPM_ADAPTER_UNAVAILABLE` instead of their stable contract codes.
3. Twelve dot-segment, separator, encoded-separator, query/fragment, control-character, and Unicode-confusable identifiers reached the transport instead of failing validation.
4. A successful durable decision left the non-production cache at `pending` instead of `approved`.

The complete pytest failure output remains available in the originating Codex task transcript. This evidence file intentionally excludes credentials, response URLs, and provider bodies beyond stable contract codes.
