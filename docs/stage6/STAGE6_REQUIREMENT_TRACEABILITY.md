# Stage 6 requirement-to-evidence matrix

Baseline reconciled 2026-08-10: `main@61e456688952cda6e09574b33413b4eb1f84aac3`.
`automated_preflight` never substitutes for current-candidate production evidence.

| Requirement / gate | Current implementation | Automated evidence | Production evidence | Status at Stage 6 start |
| --- | --- | --- | --- | --- |
| FR-001 unified inbound | shared invoke service and aliases | `test_stage1_unified_contract.py` | current OpenClaw staging 5/5 | implementation present; production evidence pending |
| FR-010/130 Case and tenant | shared domain + tenant-scoped repositories and Stage 7B workbench aggregate candidate | Stage 1/2 tenant and domain tests plus `test_myaivan_workbench.py` | MyAIVAN current-candidate walkthrough | candidate present; paginated child APIs and production evidence pending |
| multi-role RBAC | canonical role/capability/transition policy | Stage 2 role/RBAC tests | role-switch adversarial 5/5 | implementation present; production evidence pending |
| FR-050 approvals | Core draft/approval state machine | approval suites | Email/LINE/Relay current receipts | partial; Stage 5C pending |
| FR-060/100 Relay | capability registry and Core relay APIs | `test_stage4_relay.py` | real mobile WeChat 5/5 | automated only; UI/mobile evidence pending |
| FR-070 MyAIVAN | trusted session and responsive workbench candidate | `test_myaivan_workbench.py`; local mobile browser walkthrough | UI 5/5, accessibility and real-device evidence | candidate present; not production accepted |
| FR-080 Plugin/SKILL | versioned plugin, SKILL, six tools | plugin/Gateway harness | current OpenClaw staging 5/5 | implementation present; current staging evidence pending |
| FR-090 Email / LINE | capability mode exists | transport tests are not full current-candidate proof | provider receipts and failure/retry 5/5 | **Stage 5C not delivered** |
| FR-110 correction | impact/reverse and immutable ledger | Stage 5A suite; all 7 blocker codes covered | UI correction + compensation 5/5 | Core and blocker coverage present; downstream invalidation/correction draft still pending |
| FR-121 Token Guard | centralized local-model guard | `test_llm_token_guard.py` | AIVAN Qwen/Ollama capacity run | automated present; production benchmark pending |
| backup and restore | backup locations/config are operational concerns | no repository test can prove live recovery | approved isolated restore drill | pending |
| CTYun routing | existing `abcdyi-sin` bridge required | static documentation guard | route/service evidence | pending; all non-China paths must use bridge |
| port safety | 443/8443 reserved for SSH/MAIL | no code shall bind them | before/after listener evidence | pending; modification prohibited |
| release sign-off | Stage 6 PRD and tracker | CI/Claude cross-review | product/engineering/operations/supervisor signatures | pending |

## Evidence ownership

| Evidence | Responsible role | Approval required |
| --- | --- | --- |
| CI and automated five-run preflight | engineering | Claude Code cross-review |
| MyAIVAN/UI product scenarios | product + QA | product owner |
| Email/LINE/WeChat/Wangwang receipts | channel operator + QA | authorized approver |
| CTYun deployment, bridge, ports and monitoring | operations | operations owner + supervisor |
| backup restore and rollback drill | database/operations | maintenance-window approval |
| final release | project supervisor | all prior gates complete |

