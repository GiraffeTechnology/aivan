# Aivan Agent Instructions

Read this file before changing the repository.

## 1. Product authority

Issue #90 is the current product baseline for the bounded v1.0 delivery stage.

The current v1.0 product objective is an Industrial Order Execution Agent with the following delivery loop:

1. Buyer RFQ input
2. Requirement structuring
3. Supplier inquiry draft
4. Supplier reply parsing
5. GLTG invocation
6. Execution recommendation
7. Human approval

Historical PRDs, stage plans, audit issues, review comments, runbooks, commit messages, generated reports, and agent-authored interpretations are reference material only unless explicitly incorporated into #90 or a later authorized product ruling.

## 2. No autonomous product governance

Codex, Claude Code, automated reviewers, CI agents, and other tools may implement, test, review, audit, and report evidence. They do not have authority to create or expand product scope.

They MUST NOT independently:

- create a new product requirement;
- create a new delivery gate or approval gate;
- create a new stage that blocks the current bounded stage;
- convert a recommendation into a blocker;
- convert an audit observation into a product requirement;
- reinterpret historical documentation as current scope;
- add a client obligation;
- redesign the product because a broader architecture appears preferable;
- delay a demonstrable bounded delivery in order to complete unrelated later-stage infrastructure.

If a potential requirement cannot be traced to #90 or a later authorized product ruling, report it as an observation. Do not implement it as mandatory scope.

## 3. Bounded delivery rule

Aivan is delivered incrementally. Work must converge toward a finite demonstrable stage.

Use this sequence:

```text
IMPLEMENT BOUNDED SLICE
→ INTEGRATE
→ TEST
→ DEMONSTRATE
→ FREEZE THE STAGE
→ OPEN THE NEXT BOUNDED STAGE
```

Do not use this sequence:

```text
AUDIT
→ EXPAND REQUIREMENTS
→ ADD GATES
→ EXPAND ARCHITECTURE
→ DEFER DELIVERY
→ REPEAT
```

The current v1.0 stage is the seven-function loop in §1. Later capabilities must not block that loop unless they are technically required for it.

## 4. Classification for existing work

When reconciling existing code, documents, issues, or pull requests, classify material work into exactly one of these categories:

- **KEEP** — useful, compatible with #90, and safe to preserve.
- **FINISH-NOW** — required for the current v1.0 loop and close enough to completion that finishing it is the shortest delivery path.
- **FREEZE-LATER** — useful and compatible with the broader product direction, but not required to deliver the current v1.0 loop. Preserve it; stop expanding it; do not let it block the current stage.
- **REMOVE** — unsupported, contradictory, harmful, dead, duplicated, or actively creating delivery/governance conflict.

AI authorship alone is never a reason to remove useful implementation.

When uncertain between deletion and preservation, prefer FREEZE-LATER if the implementation is useful and harmless.

## 5. Preserve useful engineering

Do not perform a broad source rollback merely because previous governance expanded too far.

Preserve useful tested implementation such as authentication, tenant boundaries, workbench functionality, OpenClaw integration, GLTG integration, security fixes, observability, CI coverage, deployment safeguards, and reusable infrastructure when compatible with #90.

Remove code only when removal reduces an active product, security, maintenance, or delivery conflict.

## 6. Public-repository hygiene

This repository is public. All repository writing must be suitable for public disclosure and MUST be in English.

Do not publish:

- internal management discussions;
- blame or responsibility narratives;
- private commercial terms, budgets, quotations, or negotiations;
- credentials, secrets, private host details, or sensitive deployment information;
- private counterparty information;
- internal identity mappings;
- unnecessary AI session links or tool self-commentary.

Issues and pull requests should contain only the minimum product, engineering, security, test, or delivery information needed for public collaboration and auditability.

Internal coordination belongs outside the public repository.

## 7. OpenClaw and model boundaries

OpenClaw is a gateway/runtime integration, not the Aivan product identity.

Aivan must not be described as belonging to a specific LLM ecosystem. Model providers and models are replaceable implementation dependencies unless an authorized product ruling states otherwise.

Do not turn a currently selected model, gateway, provider, database, cloud, or external service into an architectural product identity or exclusive dependency without explicit authority.

## 8. Delivery priority

Prefer, in order:

1. a real defect that prevents or corrupts the current v1.0 loop;
2. missing integration required to complete the seven-function loop;
3. tests and evidence required to demonstrate that loop;
4. cleanup that directly removes an active blocker or contradiction;
5. later-stage work only after the current stage is frozen.

Security defects that expose data, bypass authorization, corrupt state, or turn unauthenticated input into uncontrolled server failure remain valid engineering defects and may be FINISH-NOW even when discovered by an audit.

## 9. Before handoff

Before claiming a bounded stage is complete:

- identify the exact #90 function(s) delivered;
- run the relevant tests and integration checks;
- verify the working path uses real application components rather than presentation-only fixtures where the product requires execution;
- record unresolved later-stage work as FREEZE-LATER rather than a current blocker;
- do not create a new gate while reporting completion.

The objective is convergence: preserve what works, finish the bounded product loop, freeze it, and then proceed to the next stage.