# Product Source Reconciliation

Date: 2026-10-02. This is a source-to-requirement map for the documentation cleanup. It contains no claim of code completion, permission to deploy, or transfer of private attachments into the repository.

## 1. Sources and precedence

The product owner identified A1 and A2 as the original product definitions. W1 describes the first web iteration; L1 is the detailed dependency-model iteration. Later explicit owner corrections take precedence over conflicting historical text. Source hashes identify the supplied files without publishing their original contents.

| ID | Source | SHA-256 |
| --- | --- | --- |
| A1 | Original Aivan Product Manual | `a4c23c74845b73cede88bce6c64cab74ec3ced39284b6807b701ffbc5e0ddad6` |
| A2 | Original abcdYi Product Manual | `b751b61cfaf2794d77e0ab9b900b00f2516308dc918f66ba83f1240d9f0a107d` |
| W1 | AIVAN Web First Iteration PRD | `7265a02da590d21080c96b391f98f4a05f2021348ee7c2401b6e7c4f8de218dd` |
| L1 | GLTG Trade & Processing Time Factor Model Iteration, v1.0, 2026-06-30 | `acc28b9f083041cc3f7859da3f3a3732ace2165947ba4bdb8c08b3813c30def3` |

**C1: Product-owner corrections of 2026-10-02.** Aivan is Giraffe Agent's frontend for inquiry, quotation and order confirmation; abcdYi is the apparel/textile industry application and calls Aivan at its frontend; MyAivan is Aivan's web version. OpenClaw-Aivan is the IM/email access dependency. GLTG/GPM are invoked via API. The private-domain DB is hot-swappable, dynamic and extensible, and stores history plus process state across Giraffe Agent/abcdYi/Aivan. Aivan uses DB truth, not chat context. The two designated simulated DBs are valid acceptance data sources. The independent formal-contract-before-production requirement is withdrawn.

**C2: Retained operating decisions.** `myaivan-web` is a permanent release branch and must not merge into `main`. CI must be green before a merge; that operation rule is not a new product definition or a requirement to purchase a specific scanning service. Preserve useful code and real safety/integrity controls.

**C3: Language and preservation corrections of 2026-10-02.** Standard English is the work and interaction language. Non-English input/output uses dynamic translation through `giraffe-language-skill`. Input is translated before entering product workflow. Except for enterprise/user profile information, the DB must not store non-English content. Earlier permission to retain paired non-English source text in business records is superseded. Inventory and freeze scope-expanded code for preservation; do not delete it. Translate non-English repository content into English without silently changing API contracts or treating non-English fixtures as authorized DB writes.

The existing apparel/textile focus remains. Historical references to handicrafts do not expand the current vertical into an unrelated cross-industry platform.

## 2. Adopted requirements and corrections

| Source location | Adopted outcome | Conflicting interpretation removed |
| --- | --- | --- |
| A1 sections 1-4; C1 | Digital trade assistant, inquiry through quotation and order confirmation | Monitoring/takeover alone, pre-contract-only frontend, or seven steps ending at approval as the whole product |
| A2 sections 5-8; C1 | Industry app uses shared Aivan frontend; human-confirmed order continues into industry execution | Independent formal-contract ID/version/signature as a production prerequisite |
| W1 sections 1, 6-11, 20, 24 | Welcome, Start Working, conversation/review/input layout | Operations dashboard as substitute for the web product |
| W1 sections 5, 10, 12, 17 | All IM copy/manual-send; explicit configured email with honest fallback | LINE auto-send, all-channel connectivity or all real receipts as initial web prerequisites |
| W1 sections 11, 13, 19-20 | Usable files/images; voice may be deferred; minimal safe storage | File/image placeholders until a full object-storage/scanning platform exists |
| W1 sections 14-15, 19; C1 | Simple implementation, DB-backed history/process writes and recovery, Markdown backup | localStorage/chat transcript as authoritative business state; fixed DB vendor/schema as identity |
| C1 | Two designated simulated DBs accepted using real code/APIs/writes/readback | Mandatory production-customer data; treating synthetic dataset as fake execution |
| A1 sections 2, 4, 8-9; A2 sections 5, 8 | Human control, truthful supplier facts, platform trust separate from supplier trust | Blanket deletion of approvals/security as unwanted gates |
| W1 sections 21, 24 | Five consecutive UI test runs with original 20 cases | Deleting source-defined repetition, or multiplying it into unrelated full-production checks |
| A2 section 12 | Industry-application five-run and clean-state checks remain in their own scope | Requiring its entire production/QC/logistics lifecycle to accept the first Aivan UI |
| L1 sections 1-8, 10-13 | Material/execution/behavior distinctions, quantiles, factors, explanations, four scenario tests | Slow reply means high risk; fast reply means reliable; invented material facts |
| L1 sections 4, 6.7, 9.4, 14 | Staged/rule-based first implementation; optional new table; later DAG/calibration | Complete DAG, new DB table, ML or long-term real-data calibration before usable iteration |
| C3 | English workflow and stored business content; dynamic language-skill I/O | Raw non-English business persistence, alternate translation system, fixed five-locale readiness gate |

## 3. Source tensions resolved explicitly

- A1's broad no-data-leaves-device wording conflicts with its configured remote model/search/connectivity services. The revised PRD distinguishes approved dependency processing from human-approved business messages; it does not promise impossible absolute locality.
- A1's trusted-platform contact wording does not waive its universal human review before outward business messages. A platform allowlist is not supplier approval.
- W1's simple-storage permission does not override C1's DB truth and process persistence. Choose a simple compatible provider; do not build another authoritative browser-only business store.
- Original source retention is reconciled with C3 using permissible source references/digests and canonical English, not a new raw-language field or side store.
- L1 lists uncertainty coefficients totalling 1.10 without a stated normalization convention, and lists subprocess time both within production and separately. These are technical specification issues to resolve in the model implementation with explicit tests, not new business approval gates. Do not silently copy contradictory arithmetic or claim the document alone implements a formula.

## 4. Repository document changes

| Surface | Reconciled treatment |
| --- | --- |
| Root README and AGENTS | One product identity, DB truth, language rule, actual branch/channel boundaries and source-based authority |
| AIVAN_PRODUCT_PRD.md | Full current product target, including order confirmation |
| MYAIVAN_WEB_PRD.md | Original usable conversation UI scope plus later DB/language rulings |
| ACCEPTANCE_CRITERIA.md | Observable scoped outcomes, source-defined test runs and valid simulated DB execution |
| DELIVERY_STAGE_FRAMEWORK.md | Bounded delivery guidance; no issue/stage label independently creates a product gate |
| GLTG iteration PRD and technical/transport appendices | API dependency iteration aligned to L1; preserve fifteen formula groups, stage topology, enums, schemas and tests; optional research separated from working delivery |
| ADR 0003 and responsibility matrix | Runtime implementation history distinguished from current frontend identity and replaceable DB |
| Stage 5/6/7 PRDs and trackers | Preserve useful engineering facts and safety; remove conflicting umbrella product gates and stale completion authority |
| Web branch/UI catalog documents | Separate release line, shared business; dynamic translation; prior catalog tests remain historical implementation evidence |
| Deployment documents | Scoped operational protection and authorization; no automatic product-wide Stage 7F barrier |
| OpenClaw README/SKILL, security policies and language/data contracts | Correct replaceable-DB dependency identity, human/channel semantics, dynamic English boundary and simulated-data distinction |

Historical issues, PRs and immutable commit history are not rewritten by this cleanup. Where their scope differs, they remain non-authoritative references. Existing code/tests are preserved; conflicting behaviors are listed for follow-up rather than deleted, disabled or falsely declared fixed.

## 5. Freeze and later work

[Scope preservation inventory](SCOPE_PRESERVATION_INVENTORY.md) records candidate code, original revisions, source conflicts, tests and dependencies. A preserved artifact is not automatically an approved requirement. Conversely, complexity or AI authorship alone does not establish that code is unauthorized.

Freeze expanded or unconfirmed work at its recorded revision. A protective archive ref plus a source manifest is preferable to destructive deletion or a broad rollback. Creating repository refs still requires the authorized publication step; this documentation proposal itself creates none and does not change runtime behavior.

No further product-definition question is required to perform this cleanup. Future implementation can identify its concrete delivery slice without reopening settled definitions or creating a new clarification gate.
