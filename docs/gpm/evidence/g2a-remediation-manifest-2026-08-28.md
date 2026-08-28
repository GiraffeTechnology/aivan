# G2-A remediation evidence manifest

Status: local implementation candidate; independent audit and required GitHub CI remain required.

## Frozen provenance

- PR: `#76`
- Audited remote head: `535d165dcc6f782411c76630c4ad8f54e683e97c`
- Local provenance commit: `1cc6f211f428e8c00fa1639ba1084cff833db630`
- Shared audited tree: `79bd5e529fa9c5599657f81f874710725df88464`
- Audit report SHA-256: `65A0026F4EB1892D42D6DFCF28DDCD9E08835920D551ED741E7C36A945663052`

## Remediation file hashes

| SHA-256 | File |
|---|---|
| `27C2FE2D1EE8C838A9DBBD01B47E8137F2693C7F1C99514ECDB79E59043707CD` | `src/aivan/gpm/auth.py` |
| `3E412011216E89FA3770C5DFFC5B500FF7194A7E427F442A1376CFE03B2C2F00` | `src/aivan/gpm/giraffe_db_client.py` |
| `4CE3DCF3AAE4A20F98D8C36A6C5B6268234F5BAEAD60378AE05DEEDBB1AF6434` | `src/aivan/gpm/packet_store.py` |
| `B714A92AE16B3EFCB94959BEAA49B0191F197BFD6267C03D26BE3135707134E5` | `tests/unit/gpm/test_g2a_contract.py` |
| `51784B786D80E743C47731050DB254BA965C9B8CCB5A7E9EE85BECDDE279AAEF` | `docs/gpm/evidence/g2a-security-red-2026-08-28.md` |
| `84F571440019A1A3AC23670C997392692C6CC8812672E731E0C1B4661319E1D5` | `docs/gpm/evidence/g2a-stage6-local.jsonl` |

## Local gates

- RED baseline: 17 failed, 21 passed.
- Focused contract: 42 passed.
- GPM plus Stage A: 270 passed.
- Full pytest: 888 passed, 2 skipped.
- Coverage: 83.22% (required minimum 75%).
- Ruff: passed.
- Mypy: 27 files, no issues.
- Bandit high severity: no findings.
- Compileall: passed.
- Module size budget: passed.
- Stage6 automated preflight: 5/5 consecutive passes.
- `git diff --check`: passed.

GitHub required CI, CodeQL, review-thread resolution, and independent audit are deliberately not claimed by this local manifest.
