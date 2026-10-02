# Aivan Product and Dependency Responsibility Matrix

Reconciled: 2026-10-02. The path is retained for existing links; the product is not monitoring-only. See [Aivan Product Requirements](../AIVAN_PRODUCT_PRD.md).

| Boundary | Responsibility | Required behavior | Failure handling |
| --- | --- | --- | --- |
| Aivan frontend | Inquiry, quotation, human review and order confirmation | Shared business workflow, source-grounded user-visible results | Show the precise failed step; no false completion |
| MyAivan web | Conversation/review/input UX over Aivan | Permanent independent release line, same business truth | Retain recoverable case state and honest UI status |
| abcdYi industry app | Apparel/textile rules and full industry execution | Frontend calls Aivan; industry lifecycle uses shared data semantics | Preserve actual status and permissions |
| Private-domain DB | Dynamic history and process system of record | Compatible replaceable provider, real reads/writes/readback/recovery | No chat-memory or fake-persistence fallback |
| GLTG | Lead-time and feasibility API | Use returned model/evidence contract, no duplicate local engine | Structured unavailable/invalid result, no invented lead time |
| GPM | Procurement/path reasoning API | Grounded results and durable process evidence | No fabricated recommendation/decision |
| OpenClaw-Aivan | IM/email access, account/channel connectivity | Human-approved channel actions; first-web IM remains manual | Accurate unsent/failed/unknown/mock status |
| Language module | Dynamic `giraffe-language-skill` translation | Standard-English workflow; non-English DB only for enterprise/user profiles | No raw-language business fallback or side-store exception |
| Human actor | Review, reject, revise and authorize commercial actions | Actual action, content, recipient and case remain traceable | Draft/approval is not delivery or order completion |
| Runtime engineering | Auth, isolation, integrity, safe files/logs and idempotency | Preserve protections required by selected workflow | Fail safely without corruption or secret exposure |
| Deployment operations | Authorized environment-specific changes | Separate scoped authorization and target protection | No implied deployment from docs, merge or preflight |

## Data and acceptance

The same replaceable DB truth relationship applies across Giraffe Agent, abcdYi and Aivan. Its two designated simulated DBs are valid for functional acceptance through real application/API execution. No particular database brand, production-customer dataset or named stage is an automatic prerequisite.

Persist necessary process and history records through the appropriate owner/API, using standard-English business text. References/hashes may preserve provenance without storing prohibited non-English raw business content. Do not make local control state or an LLM transcript a competing system of record.

## Existing implementation

Versioned contracts and runtime checks are useful assets. Legacy control-plane settings, fixed providers, frozen locale catalogs and stage-specific readiness behavior must be assessed against the current requirements; their existence alone does not create product scope. Preserve conflicting or unselected code in the inventory and change behavior only in scoped authorized work.
