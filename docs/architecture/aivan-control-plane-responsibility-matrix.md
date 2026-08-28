# AIVAN control-plane responsibility matrix

Status: Stage A frozen boundary
Date: 2026-08-28

This matrix is normative for the AIVAN product runtime. It does not transfer
repository development responsibility and it does not authorize production
deployment.

| Boundary | Authority / owner | AIVAN may do | AIVAN must not do | Production failure behavior |
|---|---|---|---|---|
| Business facts other than QC | `giraffe-db` | Consume an audited, versioned API/SDK contract | Treat local tables, fixtures, stubs, or generated history as authoritative | No canonical context; stop the dependent step |
| QC facts | Existing QC authority, excluded from this program | Preserve the existing boundary | Reassign QC ownership through this change | Preserve existing behavior; escalate contract ambiguity |
| Lead-time result | GLTG | Submit versioned inputs and consume returned evidence | Calculate or silently replace GLTG results locally | Mark dependency unavailable; no commercial side effect |
| Channel connectivity | OpenClaw | Consume normalized inbound events; submit an approved outbound request | Hold channel credentials outside the adapter or bypass approval | Stable error reference; remain unsent |
| Email test transport | Approved test-only adapter | Send only under its explicit allowlist and real-test mode | Become a general production fallback | Deny recipient/transport; remain unsent |
| Translation generation | `giraffe-language-skill` dedicated translator | Request canonicalization/rendering and verify provider provenance | Use qwen, ollama, mock, or an LLM as translation generator | Preserve source; require confirmation/takeover |
| Translation proofreading | qwen in proofread-only role | Review translator output when explicitly configured | Generate the source translation or silently replace it | Keep authoritative translator output or fail closed |
| Local model reasoning | Approved private model | Produce non-authoritative draft/advisory output | Create business facts, approve, send, or act as external translation generator | Stable unavailable state; deterministic evidence only |
| External model API | Approval/consent policy | Call only inside a scoped, active approval context | Automatic call, implicit fallback, or secret-bearing telemetry | Deny before network call |
| Monitoring and takeover state | AIVAN | Persist control state and audit evidence; later implement Stage B/C state machines | Claim Stage B/C closure during Stage A | Not-ready / no side effect |
| Local persistence | AIVAN control-plane store | Store control, audit, or an explicit cache/projection with provenance, TTL, invalidation, and rebuild rules | Become a second system of record | Reject production canonical-context construction until Stage D |
| Code and repository operations | Development toolchain outside runtime | None in the packaged product | Generate/execute code, shell out, write repositories, commit, or run Git | Process startup fails when a prohibited capability is enabled |
| Deployment and infrastructure | MyAivan / authorized operations task | Produce immutable application artifacts and instructions in later stages | Login, deploy, change DNS/TLS/proxy/ports, or touch mail/MX | No remote action |

## Authorized side-effect adapters

Production business side effects are allowlisted to reviewed adapters only:

- OpenClaw outbound delivery after the shared authorization and channel-policy
  gates;
- the explicitly allowlisted email test transport, never as a general fallback;
- versioned `giraffe-db` writes after its API/SDK consumer contract is accepted
  in Stage D.

GLTG, language-skill, search, and model calls are dependency requests, not
commercial approval. Their results cannot themselves authorize sending,
approval, repository mutation, or a state transition with external effect.

## Stage A enforcement status

- API, GPM, and CLI production entry points validate the frozen runtime policy
  before mutable initialization or command dispatch.
- Production rejects mocks/stubs/test transports, automatic external-model
  calls, and enabled code/repository capability flags.
- The legacy local business-context constructor fails closed in production.
  Replacement by an accepted `giraffe-db` API/SDK is deliberately deferred to
  Stage D.
- Monitoring closure and takeover state machines are deliberately deferred to
  Stages B and C. This document is not evidence that those stages are complete.

## Error and evidence contract

Remote response bodies and exception strings are not returned to callers or
written to logs. Runtime errors use a stable category plus an opaque correlation
identifier; logs retain only that identifier, exception type, and reviewed
low-cardinality context. Secrets remain environment/secret-store inputs and are
never included in readiness output or evidence manifests.
