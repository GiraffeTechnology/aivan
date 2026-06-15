# Changelog

All notable changes to AIVAN are documented here.

## [0.1.0] — 2026-06-15

### Added

- Initial release of AIVAN — local-first AI trade salesperson assistant
- OpenClaw integration for IM/email/marketplace connectivity
- Buyer requirement structuring with multi-LLM support (mock, OpenAI, Anthropic, Google, DeepSeek, Qwen)
- Supplier sourcing: registry matching + Alibaba marketplace search
- Supplier risk screening with tiered risk levels (critical/high/medium/low/unknown)
- Lead-time estimation model with P50/P80/P90 percentiles and deadline feasibility
- Buyer option generation and comparison
- Human approval gate for all outbound messages (non-negotiable)
- Trusted platform whitelist (Alibaba, AliExpress built-in; others require approval)
- Local web dashboard at `http://127.0.0.1:8765/app`
- Append-only execution event log for full audit trail
- 181 pytest tests; all pass in mock mode without live credentials
- ClawHub code plugin bridge: `@giraffetechnology/openclaw-aivan`
- ClawHub skill listing: `aivan-trade-salesperson`
- CLI commands: `aivan init`, `aivan serve`, `aivan demo`, `aivan demo-marketplace`, `aivan demo-risk-check`
- Plugin validation and smoke test scripts
