# Target-Specific Predeployment Reference

Reconciled: 2026-10-02. The legacy Stage 7F path is retained for links. This reference is not product acceptance, a mandatory product stage, or permission to execute host changes.

## Before an authorized deployment

Identify the actual target and exact candidate revision. Observe current branch/service/route and the selected DB provider/profile; do not assume historical August topology is current. Preserve the permanent `myaivan-web` release boundary. CI must be green before merge; deployment requires its own authorization.

Determine changes, safe recovery/rollback and data backup needs for this specific operation. Use least-privilege credentials from the approved store. Do not disclose raw secrets or private rows in evidence.

For the CTYun Aivan target, retain existing protected-port/service and `abcdyi-sin` routing restrictions in [the safety notice](../DEPLOY_OPENCLAW_AIVAN_SOP.md). A failed readiness check is a real observation to investigate, not permission to take over protected services or bypass the route.

## Existing predeployment tool

`scripts/run_stage7f_predeployment.py` produces the existing `production_predeployment` evidence class with `production_acceptance=false`. It is not deployment or application-function evidence. Its fixed-profile inputs and historical prerequisites are implementation constraints to inspect against the selected target; this document does not change the runner or order every old stage check for every delivery.

For a target that actually uses the existing migration tooling, preview the plan, preserve a verified recoverable backup where changes require it, apply only within authorization, and verify convergence/readback. A different compatible private DB provider may need a different reviewed migration or no migration. Do not force one physical schema solely because this historical script used it.

## After activation, if authorized

Record the actual deployed SHA, selected dependency/provider versions, relevant health/session/data checks and the user flow exercised on that target. Verify DB process state/readback and correct authorization/channel behavior. If the change fails, follow the authorized recovery plan and report the failed candidate honestly.

The two designated simulated DBs are valid functional acceptance sources. A deployment observation does not turn a simulated dataset into production-customer data, and it need not do so. Conversely, a local mock transport or skipped test is not a live integration pass.

Use [Acceptance Criteria](../ACCEPTANCE_CRITERIA.md) and [MyAivan requirements](../MYAIVAN_WEB_PRD.md), including their five-run UI scope. Do not add an all-live-channel, full-operations or multi-signature prerequisite from the historical Stage 7F label.
