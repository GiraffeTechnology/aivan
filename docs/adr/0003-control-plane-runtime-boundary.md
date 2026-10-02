# ADR 0003: Frontend Runtime and Data Responsibility

Status: Reconciled with product-owner corrections on 2026-10-02. This replaces the former monitoring-only identity and mandatory Stage A-D cutover interpretation. Existing runtime code is preserved, not changed by this ADR.

## Context and decision

Aivan is Giraffe Agent's frontend for inquiry, quotation and order confirmation. Monitoring/takeover are possible capabilities, not the entire product. The private-domain DB is the dynamic, extensible system of record for both business history and process state. giraffe-db is one replaceable provider; a user's compatible private DB is allowed.

Aivan obtains facts from that provider, writes successful process changes through the proper service contract, and recovers from DB state across conversation switches/restarts. It does not reconstruct business truth from chat/LLM context or a browser cache. A provider-derived context object is legitimate input.

GLTG and GPM are API dependencies. OpenClaw-Aivan provides IM/email access. Standard English is the work/interaction language, with dynamic language-skill translation before non-English input enters workflow. Non-English DB content is prohibited except enterprise/user profile information.

## Existing runtime policy versus product definition

The historical runtime has literal settings such as `monitoring_takeover_control_plane` and `control_audit_cache_only`, plus a production context guard. These identify existing implementation behavior; they are not current product identity or authorization to require a named Stage D before delivering a compatible DB provider.

If a guard blocks the required real provider/API flow, fix that specific mismatch in authorized code work while preserving authentication, isolation, no-fabrication and durable-state behavior. Do not disable every guard or claim the documentation itself repaired the implementation.

The two designated simulated DBs are legitimate acceptance sources. Executing the real application/API path against them is different from fake HTTP transports, invented histories or uncommitted memory persistence. Keep simulated labels and truthful evidence; do not reject the valid dataset merely for being simulated.

## Preserved runtime safety

- Human approval remains required for external business messages and consequential commercial actions.
- Trusted server-side identity, tenant/object authorization and idempotency remain necessary.
- An unavailable DB/API must not yield fabricated facts, claimed commits or false delivery.
- Account credentials and secrets remain outside repository content and public evidence.
- Product runtime does not acquire repository-write, shell/code-execution or deployment authority from this product cleanup. Existing capability protections are preserved.
- Tests and developer tooling are distinct from production business execution; report what actually ran.

## Consequences

Keep useful tested code and expanded/unselected assets in the [preservation inventory](../SCOPE_PRESERVATION_INVENTORY.md). No code is deleted or silently disabled. A separately released web branch shares the same business model and DB truth. Current acceptance follows [the source-based criteria](../ACCEPTANCE_CRITERIA.md), not the historical monitoring-only program.
