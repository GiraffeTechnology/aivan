# Scope Preservation Inventory

Date: 2026-10-02. This is a bounded inventory of verified source conflicts and preservation references, not a claim that every file has been audited or that an entire branch is unauthorized. No runtime code, tests, configuration or original history is deleted, refactored or disabled by the PRD cleanup.

## Snapshot references

The entire source trees are preserved so work not listed below is not lost. A protective reference preserves an exact commit; it does not approve every feature, merge product branches, deploy a release or resume development.

| Snapshot | Exact source commit | Protective branch reference |
| --- | --- | --- |
| main | [`6ee2d3cf2e79df2d472149db18a08e289882cb56`](https://github.com/GiraffeTechnology/aivan/commit/6ee2d3cf2e79df2d472149db18a08e289882cb56) | [`preservation/pre-prd-cleanup-2026-10-02-main-6ee2d3c`](https://github.com/GiraffeTechnology/aivan/tree/preservation/pre-prd-cleanup-2026-10-02-main-6ee2d3c) |
| myaivan-web | [`a6852cab94b947a0f3e94425ba38ccf8b1407e2a`](https://github.com/GiraffeTechnology/aivan/commit/a6852cab94b947a0f3e94425ba38ccf8b1407e2a) | [`preservation/pre-prd-cleanup-2026-10-02-web-a6852ca`](https://github.com/GiraffeTechnology/aivan/tree/preservation/pre-prd-cleanup-2026-10-02-web-a6852ca) |
| PR117 | [`44c36a1c0e45ef41ba424b85f852d35bbc7a4cc2`](https://github.com/GiraffeTechnology/aivan/commit/44c36a1c0e45ef41ba424b85f852d35bbc7a4cc2) | [`preservation/pre-prd-cleanup-2026-10-02-pr117-44c36a1`](https://github.com/GiraffeTechnology/aivan/tree/preservation/pre-prd-cleanup-2026-10-02-pr117-44c36a1) |

Reference status: all three protective branches were created and their exact target SHAs were verified through the remote Git reference API on 2026-10-02. Existing source branches were not moved or force-updated.

## Verified inventory

Source IDs refer to [Product Source Reconciliation](PRODUCT_SOURCE_RECONCILIATION.md). A source conflict identifies the part needing reconciliation, not a license to erase the module.

| ID | Snapshot and path | Classification | Finding and preservation treatment | Source | Related tests / dependencies |
| --- | --- | --- | --- | --- | --- |
| I-01 | main / [`src/aivan/governance/runtime_policy.py`](https://github.com/GiraffeTechnology/aivan/blob/6ee2d3cf2e79df2d472149db18a08e289882cb56/src/aivan/governance/runtime_policy.py); blob `e4a3368ededdff1e02561c79bcb4229f0e323981` | Confirmed product-identity conflict | Pins `monitoring_takeover_control_plane` and `control_audit_cache_only`; current Aivan definition is the inquiry/quotation/order-confirmation frontend. Preserve the code and its safety checks; do not treat these identity literals as the new product requirement. | C1; A1 sections 1-4 | [`tests/test_stage_a_runtime_policy.py`](https://github.com/GiraffeTechnology/aivan/blob/6ee2d3cf2e79df2d472149db18a08e289882cb56/tests/test_stage_a_runtime_policy.py); API/CLI startup, configuration and authentication |
| I-02 | main / [`src/aivan/integrations/giraffe_db.py`](https://github.com/GiraffeTechnology/aivan/blob/6ee2d3cf2e79df2d472149db18a08e289882cb56/src/aivan/integrations/giraffe_db.py); blob `3dfe68232b6d79d94be1509c71c0604e4deeab3b` | Confirmed delivery-path conflict; safety purpose retained | The production `build_context` path raises `GIRAFFE_DB_CANONICAL_CONTEXT_REQUIRED`. This is a real implementation gap for a working compatible DB provider, not authority for a fixed-instance/named-stage gate. Its no-fabricated-supplier and tenant protections remain valid. | C1: replaceable DB truth/history/process | [`tests/test_giraffe_db_id_contract.py`](https://github.com/GiraffeTechnology/aivan/blob/6ee2d3cf2e79df2d472149db18a08e289882cb56/tests/test_giraffe_db_id_contract.py); RFQ execution, selected private DB adapter/API |
| I-03 | myaivan-web / [`src/aivan/app/templates/index.html`](https://github.com/GiraffeTechnology/aivan/blob/a6852cab94b947a0f3e94425ba38ccf8b1407e2a/src/aivan/app/templates/index.html); blob `901098d3744450cfb9651102e1b1f5f5b1da52f1` | Confirmed first-UI mismatch | Operations/sidebar layout and line 125 attachment/voice placeholder make file/image input unavailable pending object-storage/scanning. W1 requires conversation/review/input and usable file/image input; only voice may be deferred. Preserve UI assets; do not delete the existing workbench. | W1 sections 6-11,13,19-20 | [`tests/test_myaivan_workbench.py`](https://github.com/GiraffeTechnology/aivan/blob/a6852cab94b947a0f3e94425ba38ccf8b1407e2a/tests/test_myaivan_workbench.py); Workbench APIs, app.js, session/auth and storage |
| I-04 | myaivan-web / [`src/aivan/app/ui_catalog.py`](https://github.com/GiraffeTechnology/aivan/blob/a6852cab94b947a0f3e94425ba38ccf8b1407e2a/src/aivan/app/ui_catalog.py); blob `2ed41e404e981c87b8d1a9c9c02564868bbf56cb` | Confirmed scope/language mismatch; implementation retained | Static generated-catalog machinery and non-English mapping keys are preserved assets. Mandatory fixed locale readiness is not a product source requirement; current I/O translation is dynamic through language-skill. The catalog also retains the file/image placeholder copy. | C3; W1 file/image requirements | [`tests/test_myaivan_ui_catalogs.py`](https://github.com/GiraffeTechnology/aivan/blob/a6852cab94b947a0f3e94425ba38ccf8b1407e2a/tests/test_myaivan_ui_catalogs.py); UI catalog routes/generator, readiness integration and language service |
| I-05 | myaivan-web / [`src/aivan/app/static/app.js`](https://github.com/GiraffeTechnology/aivan/blob/a6852cab94b947a0f3e94425ba38ccf8b1407e2a/src/aivan/app/static/app.js); blob `e37df6cd891b90584b50d3dd2b3d7887c18eb021` | Confirmed repository-language cleanup candidate; not wholly out of scope | Contains non-English UI literals. Translate/reconcile the interface in scoped future work while retaining session, role, safe-rendering and actual workflow behavior. The whole file is not classified as unauthorized. | C3: English repository and product language | [`tests/test_myaivan_workbench.py`](https://github.com/GiraffeTechnology/aivan/blob/a6852cab94b947a0f3e94425ba38ccf8b1407e2a/tests/test_myaivan_workbench.py); Template, UI catalog, workbench/session APIs |

## Legitimate useful functions retained

Human review/approval, trusted identity, tenant and object isolation, idempotency, truthful delivery/persistence, safe handling, compatible DB APIs, GLTG/GPM integrations and relevant tests remain valid engineering assets. The original five-run UI requirement is retained. Complexity, a stage label or AI authorship alone does not make code unauthorized.

PR117 is preserved as a candidate snapshot, including its real DB and GLTG/GPM integration work. It is not wholly classified as out of scope and is not merged by this cleanup. Its implementation/evidence must be reconciled with the updated product baseline before the owner resumes the original development task.

## Unverified remainder and language inventory

This inventory does not claim a complete code/data-language audit. Other runtime modules, fixtures, generated artifacts, deployment scripts and their code-level language changes remain **unverified for this inventory** and are preserved by the full snapshots. Older channel capability, additional monitoring/correction work and provider-specific readiness behavior must be assessed against the selected delivery before classification; they are not automatically condemned.

Repository Markdown is updated in the documentation cleanup; non-English historical display excerpts are translated and labeled as translations, with the original bytes retained in Git history. Non-English runtime/UI/fixture strings need a separate scoped translation pass that preserves API/behavior tests. Non-English business DB records need an authorized migration/translation plan, not deletion or a raw-language side-store exception.

The inventory is sufficient to preserve these snapshots without making exhaustive new code auditing a prerequisite for the documentation correction. The product owner directs resumption of original development; this PR does not resume it.
