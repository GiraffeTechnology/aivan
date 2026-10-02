# Aivan Product Requirements

Reconciled: 2026-10-02. This document describes the delivery target, not an implementation or deployment completion claim.

## 1. Source authority

The original Aivan and abcdYi product manuals are the product definitions. The MyAivan first-web-iteration and GLTG trade-and-processing-time documents provide the corresponding detailed scopes. The product owner's subsequent explicit corrections govern where those materials conflict. [Source reconciliation](PRODUCT_SOURCE_RECONCILIATION.md) records the adopted requirements and the superseded interpretations.

An issue, PR, review, test, stage plan, runtime setting, or document calling itself a client ruling does not independently establish product authority. Historical issues #90 and #96 remain useful records of earlier bounded work; their seven-step loop and four-stage framework do not replace the current product definition or create additional prerequisites.

## 2. Product and component relationships

- **Giraffe Agent** is the common agent application foundation.
- **Aivan** is the frontend application of Giraffe Agent for **inquiry, quotation, and order confirmation**. It is a digital trade assistant that helps a businessperson structure requirements, find and assess suppliers, compare responses, prepare quotations and follow-ups, and confirm the selected order with human authorization.
- **abcdYi** is the apparel-and-textile industry application of Giraffe Agent. Its frontend calls Aivan. It contributes industry fields, participant roles and workflow rules, and supports order execution through production milestones, QC evidence, logistics, buyer sign-off, and supplier-performance updates. It does not need a competing inquiry/quotation frontend.
- **MyAivan** is the web version of Aivan. The permanent `myaivan-web` branch is a separate release line, not another business system. Its user experience is defined in [the web PRD](MYAIVAN_WEB_PRD.md).
- **OpenClaw-Aivan** is Aivan's IM and email access dependency. OpenClaw is the gateway/runtime and account-connectivity layer; IM services and email are channels.
- **GLTG and GPM** are dependency modules invoked through APIs. GLTG supplies lead-time calculation and feasibility; GPM supplies quotation/pricing guidance through its API contract. Aivan consumes their results rather than embedding duplicate engines.
- **giraffe-db** is a private-domain database implementation. It can be hot-swapped for a user's private-domain database through a compatible adapter/API. No particular vendor, physical schema, running instance, or database product defines Aivan.

A monitoring view, a takeover mechanism, an operations dashboard, or a seven-step RFQ demonstration may be useful capabilities. None is a replacement for Aivan's inquiry-to-order-confirmation product.

## 3. Users and business outcome

The user is a trade businessperson, buyer, merchandiser, or an operator coordinating buyers and suppliers. The application reduces repeated parsing, sourcing, comparison, follow-up and drafting work while retaining human control over external communication and commercial commitments.

A complete Aivan business flow lets the user:

1. Bring in a buyer inquiry, supplier reply, or instruction through a configured channel or the web interface.
2. Inspect extracted requirements, source information, uncertainties and missing fields, and provide corrections or clarification.
3. Retrieve relevant suppliers, products and history from the private-domain database; prepare supplier inquiry drafts and receive responses.
4. Compare actual quotations, quantities, terms, material/capacity facts, risks and GLTG/GPM results without inventing options.
5. Review, reject, revise and approve the buyer quotation or other outbound draft using the appropriate channel workflow.
6. Confirm the selected order through a human-authorized action, preserving the selected quotation and its relevant facts, status and audit evidence in the database.
7. Reopen the work and continue from persisted facts and process state rather than reconstructing business truth from a chat transcript.

An independent formal-contract record, signature workflow, contract ID or contract-version check is **not** an additional mandatory prerequisite for order confirmation or production. Human authorization of the actual commercial action remains required. The apparel/textile execution workflow belongs to abcdYi; its fuller lifecycle is not silently attached to acceptance of the initial web interface.

## 4. Inputs and observable outputs

| Area | Inputs | User-visible output |
| --- | --- | --- |
| Inquiry and clarification | Message, file/image, buyer instructions, stored case facts | Structured requirements, preserved source, missing-field questions |
| Sourcing and supplier review | Private-domain supplier/product/history records and authorized research evidence | Actual candidates, evidence-linked risk signals, unanswered questions |
| Supplier response | Quote, price/currency, MOQ/quantity, material/capacity, terms, lead-time statement | Comparable response fields with unknowns left unknown |
| Feasibility and reasoning | DB-derived facts and selected GLTG/GPM API contract | Returned options, P50/P80/P90 where supported, factors, risks and explanations |
| Quotation | Selected option, known costs/terms and user instructions | Reviewable buyer quotation with commitment/risk notes |
| Communication | Reviewed draft, recipient, channel and explicit action | Copy/manual-send record or accurate configured-email result |
| Order confirmation | Selected quotation and human confirmation | Persisted confirmed order/business state and audit trail |

Return only real available candidate paths, up to the requested maximum. If there are fewer than three, show that number; if none, explain why. A model estimate is not a verified delivery guarantee. Preserve supplier-stated prices and lead times separately from calculations and inference.

## 5. Database truth and replaceability

The private-domain DB is an extensible, dynamic **system of record for both business history and business-process data**. This same dependency relationship applies to Giraffe Agent, abcdYi and Aivan.

Persist the records needed to continue the workflow: cases/projects, canonical English source-message records and allowed attachment references, requirements and corrections, suppliers and quotations, dependency results and their evidence, draft versions, approval/rejection decisions, copy/send outcomes, order confirmation and execution events. The appropriate service owns its writes through the chosen provider contract; a screen or model output alone is not a committed record.

- Read current facts and process state from the DB before acting on them.
- Persist successful process changes and their audit evidence; do not claim success if the write failed or its outcome is unknown.
- Recover the case from DB records after a conversation switch or service restart.
- Treat LLM/chat context, browser memory and caches as working views, never independent truth. A DB-derived object named `context` is allowed; the prohibition concerns reliance on conversation memory as fact authority.
- Keep tenant, actor, object ownership and idempotency semantics intact across provider changes. Hot-swapping means replacing the provider through its compatible boundary, not assuming every arbitrary schema works without mapping.
- Extend dynamic fields and mappings when the business process needs them; do not hard-code one customer's schema as the product definition.

The original web brief allowed localStorage, SQLite, an existing DB or demo JSON to simplify its first UI. Under the later DB ruling, a simple durable store may be an implementation choice if it satisfies the selected DB contract and truthful recovery. Browser-only or transcript-only business state does not satisfy that ruling. A complex migration, a fixed MySQL deployment or unrelated infrastructure is not automatically required.

The two designated simulated databases, generated from real local data, are valid product test and acceptance sources. Identify which source was used and retain its simulated-data label. Do not reject acceptance because they are not production-customer data. Acceptance must still execute real application code, real selected service/API paths, committed writes and readback. A hard-coded screen, fake service response, skipped CI step or fabricated persistence is a different matter and proves no such integration.

## 6. Language and stored content

Standard English is the language of work and interaction. Non-English input is translated dynamically by `giraffe-language-skill` before it enters product workflow; Aivan consumes the canonical English structured packet. Requested non-English output uses the same module dynamically, not a second translation system or static locale bundle.

Except for enterprise/user profile information, the DB must not store non-English textual content. Business history, process state, messages, drafts, quotations, order details, attachment-derived business text, events, audit descriptions and metadata use standard English. The profile exception is narrow; it does not cover business conversations. Preserve allowed source references/hashes rather than adding raw-language/audit/side-store exceptions. Existing non-English records are inventoried for an authorized translation/migration plan, not deleted. See [the detailed language rule](GIRAFFE_INTERNAL_WORKING_LANGUAGE.md).


The DB text-language rule does not prohibit non-English file/image input or require rewriting image pixels. Translate extracted business text through the language module before workflow and storage. File references and binary inputs follow the selected safe storage/authorization boundary; they do not justify retaining prohibited raw business text in DB fields or an evasion side store.

## 7. Human action and channel behavior

All external business messages require human review and authorization. A draft, an approval and an actual delivery are distinct facts. Risk notes highlight prices, dates, payment terms, quality, order confirmation, compensation and legal/commercial commitments.

For the first MyAivan web iteration:

- **All IM channels**, including WeChat, WhatsApp, LINE and Wangwang: generate, review, copy, manually send outside Aivan, then explicitly mark manually sent. Copying is not sending. This version must not claim direct IM delivery.
- **Email**: an explicit email action opens confirmation and, when configured, attempts delivery through OpenClaw-Aivan. Show actual success, failure, unknown or mock status. When not configured, explain that and retain manual copy. No unconfigured fallback may impersonate real delivery.
- Rejecting leaves the draft unsent and supports revision/regeneration. A revised commercial message requires its own review.

Other existing adapters are reusable engineering assets. Their presence does not authorize sending or make all-channel automatic delivery a prerequisite for this web iteration.

## 8. Safety and truthful behavior

Preserve authentication, authorization, tenant isolation, input/file safety, integrity, idempotency, accurate state and secret protection needed for the selected path. Fix defects that expose data, bypass approval or corrupt state; do not delete these protections to remove unrelated delivery gates.

Account authentication belongs to the connectivity layer. Aivan keeps account metadata, not platform passwords, cookies or session tokens, and does not log credentials. It does not bypass platform access controls. Platform trust does not imply supplier trust or waive human review before contact. Unknown supplier facts remain unknown; risk findings do not become final legal, credit, sanctions or compliance judgments.

Local-first deployment is compatible with configured remote dependencies. It does not justify an absolute claim that no data ever leaves a device. Distinguish approved service processing from outward business communication, and respect data-transmission permissions in both.

## 9. Delivery and acceptance

[Acceptance criteria](ACCEPTANCE_CRITERIA.md) specify observable results. The full product target includes order confirmation. The original MyAivan first iteration remains a bounded user-interface delivery within that target; claiming its completion does not claim all abcdYi lifecycle functions or every deployment profile is complete.

Keep and finish useful existing implementation. Inventory and freeze expanded or unselected code at exact revisions; do not delete it or silently disable it. Non-English repository prose must be translated into English without unreviewed API/behavior changes. Do not add mandatory legal-contract steps, extra stages, production-customer datasets, a particular DB instance, full operational platforms, full DAG simulation, long-term statistical calibration, or every live channel to a bounded delivery unless explicitly requested or technically necessary for the exact function being delivered.

The source-defined five-run MyAivan tests remain required for that iteration. Record exact revisions, chosen database source/provider, service versions, tests actually executed and unresolved limitations. A document update, candidate, passing preflight, merged PR and deployed release are different outcomes. Report only the outcome demonstrated.
