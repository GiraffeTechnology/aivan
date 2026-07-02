# PRD — GLTG Behavioral + Statistical Lead-Time Model Refactor

**Repository for this PR:** `GiraffeTechnology/aivan`  
**Future target repositories:** `GiraffeTechnology/GLTG`, `GiraffeTechnology/abcdYi`, `GiraffeTechnology/giraffe-agent`, and any future Giraffe vertical product  
**Document type:** Iteration PRD / Codex implementation brief  
**Version:** v1.0  
**Date:** 2026-06-30  
**Status:** Ready for implementation planning  

---

## 1. Executive Summary

This PRD defines the next GLTG iteration: refactor GLTG from a simple lead-time calculator into a **behavior-aware probabilistic lead-time and risk simulation model**.

The research report recommends a hybrid architecture:

```text
Statistical baseline
+ Behavioral adjustment layer
+ Explainable fallback
+ ML / Bayesian calibration layer
```

The model must output not only one lead-time number, but a calibrated and explainable distribution:

```text
P50 / P80 / P90
base production days
base procurement days
supplier response buffer
supplier uncertainty buffer
buyer decision buffer
logistics buffer
risk buffer
deadline risk level
fallback supplier recommendation
manual review recommendation
explanation_json
```

The product architecture boundary remains strict:

```text
facts live in giraffe-db
simulation lives in GLTG
execution lives in AIVAN
```

This PR is opened in `GiraffeTechnology/aivan` first because AIVAN is currently the active standalone product and the best place to define the client contract, DTO mapping, tests, and integration boundary. After this PRD is accepted, the same contract should be forked/copied into the standalone `GLTG` service and then ported into `abcdYi` and `giraffe-agent`.

---

## 2. Why This Iteration Matters

The existing lead-time flow already separates GLTG from AIVAN. AIVAN calls GLTG as a standalone HTTP service and must not perform local lead-time math or silently fall back to local calculations.

However, the current payload is still too simple. It mainly passes:

```text
order quantity
destination
logistics mode
deadline
supplier capacity / stage days
```

That is enough for MVP feasibility, but not enough for real industrial procurement.

In real trade, lead time is affected by:

```text
supplier response delay
supplier response delay vs historical baseline
supplier quote completeness
supplier price / lead-time revisions
supplier upstream confirmation signals
supplier current load signals
buyer decision delay
buyer requirement volatility
buyer price negotiation behavior
buyer sample / payment / confirmation delay
buyer-supplier pair relationship strength
historical quoted vs actual lead-time error
```

Therefore, GLTG must become a hybrid behavioral-statistical model.

---

## 3. Current Interface Inspection Summary

### 3.1 AIVAN

AIVAN already treats GLTG as an external service.

Current client endpoints:

```text
GET  /health
GET  /version
POST /v1/lead-time/estimate
POST /v1/paths/enumerate
POST /v1/reforecast
```

Current AIVAN rules:

```text
AIVAN must not calculate lead time locally.
AIVAN must not silently replace GLTG with a local fallback.
GLTG unavailability must surface as structured errors.
```

Current limitation:

```text
AIVAN passes basic order/supplier fields but not behavior snapshots, source observation IDs, baseline references, model version, rule version, calibration metadata, or explainable adjustment components.
```

### 3.2 abcdYi

`abcdYi` also uses a GLTG-backed lead-time adapter. It maps supplier response fields into GLTG input and maps GLTG output back into `LeadTimePath`. It also states that no lead-time math should happen inside the adapter.

Current limitation:

```text
abcdYi uses supplier component days, risk flags, confidence score, completeness score, and deadline, but does not yet consume structured buyer/supplier behavior snapshots or GLTG behavioral adjustment outputs.
```

### 3.3 giraffe-agent

`giraffe-agent` contains a similar standalone GLTG HTTP client and should remain compatible with the new API contract.

Current limitation:

```text
giraffe-agent uses the same simple GLTG v1 client shape. It should later adopt the same v2 contract defined by this PRD.
```

### 3.4 giraffe-db

`giraffe-db` PR#10 has introduced the structured behavior database foundation required by this model:

```text
communication_events
behavior_observations
buyer_behavior_feature_snapshots
supplier_behavior_feature_snapshots
buyer_supplier_behavior_metrics
leadtime_observations
gltg_simulation_runs
gltg_behavior_inputs
pricing_decision_inputs
data_lineage
audit_records
```

GLTG should consume snapshots and observations from giraffe-db. AIVAN should not duplicate canonical behavior facts locally.

---

## 4. Goals

### 4.1 Product Goals

1. Produce probabilistic lead-time estimates rather than a single deterministic number.
2. Make supplier and buyer behavior a first-class input.
3. Preserve explainability for every lead-time adjustment.
4. Support pricing strategy and supplier-routing decisions.
5. Keep AIVAN as execution layer only.
6. Keep GLTG as the simulation source.
7. Keep giraffe-db as the business fact source.
8. Provide a cross-repository contract usable by AIVAN, abcdYi, and giraffe-agent.

### 4.2 Engineering Goals

1. Define GLTG v2 request/response schema.
2. Update AIVAN GLTG client DTOs to support v2 payloads.
3. Preserve v1 backward compatibility during migration.
4. Add contract tests with mock GLTG service.
5. Add behavior-aware mapping from AIVAN/giraffe-db context to GLTG v2 payload.
6. Add output mapping into existing AIVAN RFQ/LeadTime DTOs without breaking current flows.
7. Store `gltg_run_id`, `model_version`, `rule_version`, and `explanation_json`.
8. Add clear integration notes for abcdYi and giraffe-agent.

---

## 5. Non-Goals

This PRD does not require AIVAN to implement the final GLTG math locally.

Do not:

```text
implement statistical lead-time calculation inside AIVAN
implement ML models inside AIVAN
copy giraffe-db canonical behavior tables into AIVAN
make LLMs invent lead-time facts
silently fall back to local lead-time calculation when GLTG is unavailable
make AIVAN the source of canonical GLTG simulation records
```

The immediate implementation in AIVAN should be:

```text
client contract
DTOs
payload mapper
response mapper
mock tests
integration documentation
```

The actual service-side GLTG model implementation should later be implemented in the standalone `GLTG` repository using the same API contract.

---

## 6. Core Model Concept

GLTG v2 should model total planning lead time as:

```text
Total Planning Lead Time
= Base Lead-Time Distribution
+ Behavioral Central Shift
+ Behavioral Uncertainty Inflation
+ Fallback / Risk Guardrails
```

More specifically:

```text
T_total
= T_requirement_confirmation
+ T_supplier_response
+ T_quote_confirmation
+ T_material_procurement
+ T_production
+ T_qc
+ T_logistics
+ T_buyer_decision
+ T_risk_buffer
```

The output must be distributional:

```text
P50 = median planning lead time
P80 = conservative planning lead time
P90 = high-confidence planning lead time
```

---

## 7. Model Architecture

```text
RFQ / Quote / PO / Communication Events
        │
        ├── giraffe-db behavior materialization
        │       ├── behavior_observations
        │       ├── buyer_behavior_feature_snapshots
        │       ├── supplier_behavior_feature_snapshots
        │       └── buyer_supplier_behavior_metrics
        │
        ├── GLTG Statistical Baseline
        │       ├── category / route / quantity baseline
        │       ├── supplier historical baseline
        │       ├── buyer-supplier pair baseline
        │       └── leadtime_observations
        │
        ├── GLTG Behavioral Adjustment Layer
        │       ├── supplier response delay anomaly
        │       ├── quote completeness
        │       ├── revision behavior
        │       ├── upstream dependency signal
        │       ├── current load signal
        │       ├── buyer decision delay
        │       └── buyer requirement volatility
        │
        ├── Hybrid Quantile Composer
        │       ├── P50
        │       ├── P80
        │       └── P90
        │
        ├── Explainable Fallback Guard
        │       ├── missing baseline handling
        │       ├── missing behavior handling
        │       ├── monotonic quantile repair
        │       └── manual review triggers
        │
        └── Persisted GLTG run
                ├── gltg_run_id
                ├── model_version
                ├── rule_version
                ├── explanation_json
                └── source_observation_ids
```

---

## 8. Statistical Baseline Design

### 8.1 Baseline Options

GLTG v2 should support two statistical baseline approaches.

#### Option A — Direct Quantile Regression

Directly estimate conditional quantiles:

```text
Q_tau(T | X), tau ∈ {0.5, 0.8, 0.9}
```

Recommended training loss:

```text
L_tau(y, q) = (tau - 1{y < q}) * (y - q)
L = Σ_i Σ_tau w_tau * L_tau(y_i, q_i(tau))
```

Initial weights:

```text
w_0.5 = 1.0
w_0.8 = 1.2
w_0.9 = 1.5
```

This is useful when there are enough actual lead-time observations.

#### Option B — AFT / Survival Baseline

Use Accelerated Failure Time modeling when some PO/fulfillment cases are incomplete or right-censored.

Generic form:

```text
log T = η(X) + σW
```

Example log-normal AFT quantile:

```text
Q_tau = exp(η + σ * Φ^-1(tau))
```

This is useful when:

```text
some orders are still open
actual delivery time is not finalized
we know the order has taken at least N days but not the final lead time
```

### 8.2 Bayesian / Hierarchical Partial Pooling

The model must eventually support partial pooling by:

```text
supplier_id
buyer_id
buyer_supplier_pair
product_category_id
route
quantity band
logistics mode
season
```

Purpose:

```text
avoid overfitting sparse suppliers
borrow strength from category / route groups
stabilize estimates for long-tail suppliers and buyers
```

A simple initial hierarchy:

```text
global baseline
  → category baseline
    → route/category baseline
      → supplier/category baseline
        → buyer-supplier pair adjustment
```

---

## 9. Behavioral Adjustment Design

Behavioral adjustment must separate:

```text
central shift
uncertainty inflation
risk flags
manual review triggers
```

### 9.1 Pseudo-Lognormal Composer

When baseline quantiles are available, convert baseline quantiles into pseudo-lognormal parameters:

```text
μ = log(P50_baseline)
σ ≈ (log(P90_baseline) - log(P50_baseline)) / Φ^-1(0.9)
```

Then apply behavior adjustments:

```text
μ* = μ + Δμ
σ* = clip(σ * exp(Δσ), σ_min, σ_max)
```

Final quantiles:

```text
P50 = exp(μ*)
P80 = exp(μ* + σ* * Φ^-1(0.8))
P90 = exp(μ* + σ* * Φ^-1(0.9))
```

This matters because some behavior signals mainly move the median while others mainly increase uncertainty.

Example:

```text
Supplier says production is 28 days but reply is slow:
  may add central shift

Supplier quote misses material availability:
  should inflate P80/P90 more than P50
```

### 9.2 Deterministic Fallback Composer

If distribution metadata is unavailable:

```text
P50 = base_p50 + shift_buffer
P80 = base_p80 + shift_buffer + 0.8 * uncertainty_buffer
P90 = base_p90 + shift_buffer + 1.2 * uncertainty_buffer
```

Always run monotonic repair:

```text
P50 <= P80 <= P90
```

---

## 10. Behavioral Feature Set

### 10.1 Supplier Behavior Features

Minimum supplier features:

```text
supplier_id
feature_window
current_case_avg_response_seconds
historical_avg_response_seconds
response_delay_ratio
business_hours_delay_ratio
after_hours_response_rate
working_hours_slow_response_rate
quote_completeness_score
missing_quote_fields
quote_revision_count
price_revision_count
lead_time_revision_count
upstream_confirmation_signal
supplier_current_load_signal
engagement_score
quote_response_rate
historical_on_time_delivery_rate
historical_quoted_vs_actual_error_days
lead_time_confidence_score
price_stability_score
```

### 10.2 Buyer Behavior Features

Minimum buyer features:

```text
buyer_id
feature_window
current_case_response_latency_seconds
historical_response_latency_seconds
buyer_response_delay_ratio
buyer_decision_delay_score
requirement_change_count
requirement_volatility_score
price_negotiation_intensity
lead_time_sensitivity_score
quality_sensitivity_score
sample_confirmation_delay_score
payment_delay_risk
historical_rounds_to_po
current_case_round_count
conversion_probability
no_response_after_quote_rate
```

### 10.3 Buyer-Supplier Pair Features

Minimum pair features:

```text
buyer_id
supplier_id
window_type
pair_rfq_count
pair_quote_count
pair_po_count
pair_conversion_rate
avg_rounds_to_po
avg_supplier_response_seconds
avg_buyer_response_seconds
avg_price_gap_vs_buyer_target
avg_leadtime_gap_vs_buyer_target
relationship_strength_score
recommended_pairing_score
dispute_count
quality_issue_count
on_time_delivery_rate
```

---

## 11. Initial Rule Table for MVP

The first implementation should be deterministic and explainable. ML calibration can come later.

### 11.1 Supplier Response Delay

```text
response_delay_ratio < 1.2:
  +0 supplier_response_buffer_days
  +0 uncertainty

1.2 <= response_delay_ratio < 2.0:
  +1 supplier_response_buffer_days
  +0.03 Δσ

2.0 <= response_delay_ratio < 3.0:
  +2 supplier_response_buffer_days
  +0.07 Δσ

response_delay_ratio >= 3.0:
  +3 to +5 supplier_response_buffer_days
  +0.12 Δσ
  risk_level +1
  consider fallback supplier
```

### 11.2 Business-Hours Delay

```text
business_hours_delay_ratio < 1.5:
  no adjustment

1.5 <= business_hours_delay_ratio < 3.0:
  +1 supplier_response_buffer_days

business_hours_delay_ratio >= 3.0:
  +2 supplier_response_buffer_days
  manual_review_if_deadline_tight = true
```

### 11.3 Quote Completeness

```text
quote_completeness_score >= 0.90:
  no adjustment

0.70 <= quote_completeness_score < 0.90:
  +1 supplier_uncertainty_buffer_days

0.50 <= quote_completeness_score < 0.70:
  +2 supplier_uncertainty_buffer_days
  +0.08 Δσ

quote_completeness_score < 0.50:
  +3 supplier_uncertainty_buffer_days
  +0.15 Δσ
  manual_review_required = true
```

### 11.4 Quote Revisions

```text
lead_time_revision_count = 0:
  no adjustment

lead_time_revision_count = 1:
  +1 supplier_uncertainty_buffer_days

lead_time_revision_count >= 2:
  +3 supplier_uncertainty_buffer_days
  reduce lead_time_confidence_score
  manual_review_required = true
```

### 11.5 Upstream Confirmation Signal

Signals:

```text
need to ask fabric mill
need material confirmation
waiting for production confirmation
need boss approval
price not confirmed
material availability pending
```

Adjustment:

```text
upstream_confirmation_signal < 0.3:
  no adjustment

0.3 <= signal < 0.7:
  +1 to +2 supplier_uncertainty_buffer_days

signal >= 0.7:
  +3 supplier_uncertainty_buffer_days
  fallback_supplier_required = true if deadline is tight
```

### 11.6 Buyer Requirement Volatility

```text
requirement_change_count = 0:
  no adjustment

requirement_change_count = 1:
  +1 to +2 buyer_decision_buffer_days

requirement_change_count >= 2:
  +3 to +7 buyer_decision_buffer_days
  increase risk level
```

### 11.7 Buyer Decision Delay

```text
buyer_decision_delay_score < 0.3:
  no adjustment

0.3 <= score < 0.7:
  +1 to +3 buyer_decision_buffer_days

score >= 0.7:
  +4 to +7 buyer_decision_buffer_days
  pricing service cost buffer recommended
```

---

## 12. GLTG v2 API Contract

### 12.1 Endpoint Strategy

Keep existing v1 endpoints for compatibility:

```text
POST /v1/lead-time/estimate
POST /v1/paths/enumerate
POST /v1/reforecast
```

Add v2 endpoint:

```text
POST /v2/lead-time/simulate
POST /v2/paths/enumerate
POST /v2/reforecast
```

AIVAN should support:

```text
GLTG_API_VERSION=v1|v2
```

Default for this iteration:

```text
v1 remains default until GLTG service supports v2.
v2 can be enabled in tests with mock transport.
```

### 12.2 v2 Request Schema

```json
{
  "request_id": "REQ_xxx",
  "tenant_id": "tenant_default",
  "source_system": "aivan",
  "source_trace_id": "COMM_xxx",

  "case_context": {
    "procurement_case_id": "GDB_SYN_V1_CASE_000001",
    "rfq_id": "GDB_SYN_V1_RFQ_000001",
    "quote_id": "GDB_SYN_V1_QUOTE_000001",
    "po_id": null,
    "buyer_id": "GDB_SYN_V1_BUYER_000001",
    "supplier_id": "GDB_SYN_V1_SUP_000001"
  },

  "order": {
    "product_category_id": "GDB_SYN_V1_CAT_000001",
    "product_id": null,
    "product_type": "apparel",
    "product_name": "white cotton shirt",
    "quantity": 10000,
    "quantity_unit": "pcs",
    "material": "100% cotton",
    "process_complexity": "standard",
    "customization_level": "medium",
    "destination": "Vancouver",
    "logistics_mode": "sea",
    "deadline_days": 45,
    "target_delivery_date": null,
    "quality_requirement_level": "standard",
    "packaging_requirement_level": "standard"
  },

  "supplier": {
    "supplier_id": "GDB_SYN_V1_SUP_000001",
    "name": "Supplier A",
    "capacity_per_day": 500,
    "material_ready_days": null,
    "production_days": null,
    "qc_days": null,
    "logistics_days": null,
    "supplier_stated_lead_time_days": 28,
    "confidence": 0.7
  },

  "historical_baseline": {
    "baseline_source": "supplier_category_route",
    "sample_size": 48,
    "baseline_p50_days": 32,
    "baseline_p80_days": 39,
    "baseline_p90_days": 45,
    "historical_quoted_vs_actual_error_days": 4.2,
    "on_time_delivery_rate": 0.78
  },

  "behavior_features": {
    "buyer_snapshot_id": "GDB_SYN_V1_BEHAVIOR_000101",
    "supplier_snapshot_id": "GDB_SYN_V1_BEHAVIOR_000102",
    "pair_metric_id": "GDB_SYN_V1_BEHAVIOR_000103",

    "supplier": {
      "response_delay_ratio": 3.0,
      "business_hours_delay_ratio": 2.5,
      "quote_completeness_score": 0.65,
      "lead_time_revision_count": 1,
      "price_revision_count": 0,
      "upstream_confirmation_signal": 0.57,
      "supplier_current_load_signal": 0.68,
      "engagement_score": 0.42
    },

    "buyer": {
      "requirement_change_count": 2,
      "requirement_volatility_score": 0.7,
      "buyer_decision_delay_score": 0.55,
      "price_negotiation_intensity": 0.8,
      "conversion_probability": 0.42
    },

    "pair": {
      "pair_conversion_rate": 0.35,
      "relationship_strength_score": 0.62,
      "recommended_pairing_score": 0.58
    }
  },

  "source_observation_ids": [
    "GDB_SYN_V1_OBS_000001",
    "GDB_SYN_V1_OBS_000002"
  ],

  "constraints": {
    "lead_time_confidence": "P80",
    "fallback_supplier_policy": "recommend_if_risk_high",
    "manual_review_policy": "required_if_deadline_tight",
    "max_acceptable_risk_level": "medium"
  }
}
```

### 12.3 v2 Response Schema

```json
{
  "ok": true,
  "gltg_run_id": "GDB_SYN_V1_GLTG_000001",
  "model_version": "gltg-hybrid-v0.1.0",
  "rule_version": "behavior-rules-v0.1.0",
  "calibration_version": "none",

  "quantiles": {
    "p50_days": 38,
    "p80_days": 43,
    "p90_days": 48
  },

  "components": {
    "base_production_days": 28,
    "base_procurement_days": 3,
    "supplier_response_buffer_days": 3,
    "supplier_uncertainty_buffer_days": 2,
    "buyer_decision_buffer_days": 4,
    "logistics_buffer_days": 5,
    "risk_buffer_days": 2
  },

  "risk": {
    "deadline_risk_level": "medium_high",
    "confidence_score": 0.68,
    "fallback_supplier_required": true,
    "manual_review_required": true,
    "deadline_feasible": true,
    "selected_confidence_days": 43
  },

  "explanation_json": {
    "summary": "P80 is recommended because supplier behavior is slower than historical baseline and quote completeness is low.",
    "adjustments": [
      {
        "feature": "supplier_response_delay_ratio",
        "value": 3.0,
        "baseline": "supplier historical average",
        "adjustment": "+3 supplier_response_buffer_days",
        "reason": "Supplier response is 3.0x slower than its historical baseline.",
        "source_observation_ids": ["GDB_SYN_V1_OBS_000001"]
      },
      {
        "feature": "quote_completeness_score",
        "value": 0.65,
        "adjustment": "+2 supplier_uncertainty_buffer_days",
        "reason": "Quote is missing confirmed lead time or material availability.",
        "source_observation_ids": ["GDB_SYN_V1_OBS_000002"]
      }
    ]
  },

  "warnings": [
    {
      "code": "SUPPLIER_RESPONSE_DELAY_ANOMALY",
      "severity": "medium",
      "message": "Supplier current response speed is slower than historical baseline."
    }
  ],

  "persistence": {
    "persisted_to_giraffe_db": true,
    "gltg_behavior_input_id": "GDB_SYN_V1_GLTG_000002"
  }
}
```

### 12.4 Backward-Compatible v1 Mapping

If only v1 response exists, AIVAN maps:

```text
data.p50_days → p50_days
data.p80_days → p80_days
data.p90_days → p90_days
data.risk_level → deadline_risk_level
data.estimated_lead_time_days → calculated_lead_time_days
data.calculation_trace → components
```

If v2 response exists, AIVAN maps:

```text
quantiles.p50_days → p50_days
quantiles.p80_days → p80_days
quantiles.p90_days → p90_days
components.* → LeadTimeComponent / GLTGSimulation components
risk.deadline_risk_level → deadline_risk_level
risk.selected_confidence_days → selected_confidence_days
explanation_json → explanation / persisted JSON
gltg_run_id → persisted reference in RFQ/project payload
```

---

## 13. AIVAN Implementation Requirements

### 13.1 Add GLTG API Version Support

Environment:

```text
GLTG_API_VERSION=v1|v2
```

Default:

```text
v1
```

Behavior:

```text
v1 mode uses existing endpoints.
v2 mode uses /v2/lead-time/simulate.
No local fallback is allowed.
```

### 13.2 Add v2 DTOs / Typed Payload Builders

Add schemas or typed dictionaries for:

```text
GLTGCaseContext
GLTGOrderInput
GLTGSupplierInput
GLTGHistoricalBaseline
GLTGBehaviorFeatures
GLTGSimulationRequestV2
GLTGSimulationResponseV2
GLTGQuantiles
GLTGComponentBreakdown
GLTGRiskOutput
GLTGExplanation
```

### 13.3 Add Context Mapper

AIVAN must be able to build v2 payload from:

```text
BuyerRequirement
RFQStrategy
GiraffeContext
supplier candidates
supplier replies
giraffe-db behavior snapshots
giraffe-db leadtime observations
current procurement_case_id / rfq_id / quote_id where available
```

If a field is missing, use `null` and include a warning/missing input flag. Do not invent facts.

### 13.4 Add giraffe-db Feature Snapshot Consumer

AIVAN should call giraffe-db for:

```text
buyer_behavior_feature_snapshot
supplier_behavior_feature_snapshot
buyer_supplier_behavior_metrics
leadtime_observations
price_observations if pricing uses them later
```

If giraffe-db structured APIs are unavailable, AIVAN should:

```text
surface structured dependency error
continue only in v1 fallback mode if explicitly configured
never synthesize canonical behavior facts
```

### 13.5 Persist GLTG References

AIVAN should persist in its execution state:

```text
gltg_run_id
model_version
rule_version
selected_confidence_days
deadline_risk_level
fallback_supplier_required
manual_review_required
explanation_json
source_observation_ids
```

Short-term location:

```text
Project.requirement_json["gltg_simulation_v2"]
```

Long-term location:

```text
giraffe-db.gltg_simulation_runs
giraffe-db.gltg_behavior_inputs
```

### 13.6 No Local GLTG Math

AIVAN may map fields and validate payloads, but must not calculate GLTG lead-time.

Allowed:

```text
payload construction
response validation
response mapping
error handling
schema compatibility
mock transport testing
```

Forbidden:

```text
local statistical model
local lead-time fallback
LLM-generated lead-time estimates
local behavior fact synthesis
```

---

## 14. abcdYi Integration Requirements

After AIVAN PR is accepted, copy/port the same contract into `GiraffeTechnology/abcdYi`.

Required changes:

```text
src/integrations/gltg_client.py
src/integrations/gltg_leadtime.py
src/b_side/feasibility_engine.py
src/m_side/rollup/supplier_response_rollup.py
tests for GLTG v2 payload and output mapping
```

abcdYi must preserve:

```text
No lead-time math in adapter.
No local fallback on GLTG failure.
P80 remains conservative feasibility basis unless overridden.
Evidence refs must include GLTG run ID and source observation IDs.
```

New fields to map into `LeadTimePath`:

```text
gltg_run_id
model_version
rule_version
p50_days
p80_days
p90_days
supplier_response_buffer_days
supplier_uncertainty_buffer_days
buyer_decision_buffer_days
deadline_risk_level
fallback_supplier_required
manual_review_required
explanation_json
```

---

## 15. giraffe-agent Integration Requirements

After AIVAN PR is accepted, copy/port the same contract into `GiraffeTechnology/giraffe-agent`.

Required changes:

```text
src/integrations/gltg_client.py
src/integrations/gltg_leadtime.py
src/b_side/feasibility_engine.py
src/m_side/rollup/supplier_response_rollup.py
buyer option generation tests
E2E trade salesperson flow tests
```

giraffe-agent must preserve the same behavior:

```text
GLTG service owns simulation.
giraffe-agent adapter owns mapping only.
No local lead-time math.
No silent fallback.
```

---

## 16. giraffe-db Interface Requirements

GLTG v2 depends on structured giraffe-db behavior tables.

Minimum required read inputs:

```text
communication_events
behavior_observations
buyer_behavior_feature_snapshots
supplier_behavior_feature_snapshots
buyer_supplier_behavior_metrics
leadtime_observations
rfq_outcomes
supplier_quotes
supplier_quote_line_items
```

Minimum required write outputs:

```text
gltg_simulation_runs
gltg_behavior_inputs
data_lineage
audit_records
```

AIVAN should not write raw GLTG results only into local JSON if giraffe-db is available. The local AIVAN state may keep a copy/reference for workflow continuity.

---

## 17. Testing Requirements

### 17.1 Unit Tests

Add tests for:

```text
GLTG v2 request builder includes case_context.
GLTG v2 request builder includes behavior_features when available.
GLTG v2 request builder includes source_observation_ids.
GLTG v2 response maps quantiles into existing DTOs.
GLTG v2 response maps risk and explanation fields.
GLTG v1 compatibility remains intact.
GLTG unavailability still raises/surfaces structured error.
No local fallback calculation is used.
```

### 17.2 Mock Transport Tests

Use `httpx.MockTransport` to test:

```text
/v2/lead-time/simulate success response
/v2/lead-time/simulate validation error
/v2/lead-time/simulate timeout
/v2/lead-time/simulate invalid JSON
```

### 17.3 Behavior-Specific Tests

Test examples:

```text
supplier response delay ratio is included in payload.
quote completeness score is included in payload.
buyer requirement change count is included in payload.
source observation IDs are preserved.
manual_review_required from response is mapped into AIVAN result.
fallback_supplier_required from response is mapped into AIVAN result.
```

### 17.4 Regression Tests

Existing tests must continue to pass:

```text
tests/test_gltg_client.py
tests/test_gltg_client_integration.py
tests/test_rfq_execution_iteration.py
tests/test_buyer_option_agent.py
```

### 17.5 Cross-Repository Contract Tests

Define a shared fixture:

```text
tests/fixtures/gltg_v2_simulation_request.json
tests/fixtures/gltg_v2_simulation_response.json
```

This fixture should later be copied to:

```text
abcdYi
giraffe-agent
GLTG
```

All repositories must agree on:

```text
request schema
response schema
field names
error envelope
model_version
rule_version
explanation_json
source_observation_ids
```

---

## 18. Acceptance Criteria

This iteration is accepted when:

1. AIVAN contains this PRD in `docs/`.
2. AIVAN has a clear GLTG v2 client contract.
3. AIVAN can build GLTG v2 behavior-aware payloads.
4. AIVAN can parse GLTG v2 probabilistic response.
5. AIVAN preserves v1 backward compatibility.
6. AIVAN does not calculate lead time locally.
7. AIVAN does not silently fall back when GLTG fails.
8. AIVAN maps `P50/P80/P90`, risk, buffers, and explanation fields.
9. AIVAN can include buyer/supplier behavior snapshots when available.
10. AIVAN can include source observation IDs.
11. AIVAN can persist or reference `gltg_run_id`.
12. Tests pass.
13. The same contract is documented for later porting to `abcdYi` and `giraffe-agent`.

---

## 19. Implementation Phases

### Phase 0 — Documentation PR

Current PR.

Deliverable:

```text
docs/GLTG_BEHAVIORAL_STATISTICAL_MODEL_ITERATION_PRD.md
```

### Phase 1 — AIVAN Client Contract

Implement:

```text
GLTG_API_VERSION
v2 DTOs
v2 request builder
v2 response parser
v1 compatibility wrapper
mock fixture tests
```

### Phase 2 — AIVAN giraffe-db Feature Integration

Implement:

```text
read buyer behavior snapshot
read supplier behavior snapshot
read buyer-supplier pair metrics
read leadtime observations
include source_observation_ids
```

### Phase 3 — AIVAN RFQ Flow Integration

Wire v2 GLTG into:

```text
RFQ creation
supplier quote parsing
buyer option generation
supplier fallback recommendation
manual review logic
pricing input generation
```

### Phase 4 — Standalone GLTG Service

In `GiraffeTechnology/GLTG`, implement:

```text
/v2/lead-time/simulate
statistical baseline
behavior adjustment rule engine
fallback composer
explanation_json
giraffe-db persistence of gltg_simulation_runs
```

### Phase 5 — abcdYi / giraffe-agent Port

Copy the shared contract and adapters into:

```text
GiraffeTechnology/abcdYi
GiraffeTechnology/giraffe-agent
```

### Phase 6 — Statistical / ML Calibration

Implement:

```text
rolling-origin backtest
pinball loss
P80/P90 coverage
quantile crossing repair
Bayesian / hierarchical calibration
residual calibration
```

---

## 20. Metrics and Backtesting

### 20.1 Forecast Accuracy Metrics

Track:

```text
P50 MAE
P50 median error
weighted pinball loss
P80 coverage
P90 coverage
coverage calibration error
sharpness / interval width
quantile crossing rate
```

### 20.2 Operational Metrics

Track:

```text
GLTG service availability
P95 latency
fallback rate
manual review rate
persist success rate
missing feature rate
behavior snapshot availability
source observation availability
```

Suggested initial latency targets:

```text
online fast path P95 <= 500ms
on-demand slow path P95 <= 2s
```

### 20.3 Data Readiness Thresholds

Suggested minimum data thresholds:

```text
MVP rule-based version:
  may run with sparse data and fallback rules

Statistical baseline:
  at least 300 completed actual leadtime observations

Hybrid statistical + behavior model:
  at least 1,000 completed actual leadtime observations
  at least 30 active suppliers
  at least 3 major category/route combinations

ML calibration:
  after stable rolling backtest and sufficient outcome labels
```

These are engineering guardrails, not external standards.

---

## 21. Risk Controls

### 21.1 Semantic Risk

Slow supplier response does not always mean low engagement. It may indicate:

```text
timezone mismatch
holiday
upstream material confirmation
internal approval
large-order seriousness
capacity pressure
low priority
```

Therefore, GLTG must treat behavior signals as risk signals, not hard facts.

### 21.2 Data Quality Risk

Every behavior feature must preserve:

```text
source observation IDs
source communication event IDs
confidence
feature window
baseline used
sample size
```

### 21.3 Black-Box Risk

Every high-impact adjustment must have an explanation.

No opaque lead-time number is acceptable for user-facing trade execution.

### 21.4 Product Boundary Risk

AIVAN must not become a hidden GLTG implementation. The boundary must remain:

```text
AIVAN = execution and client orchestration
GLTG = simulation
giraffe-db = facts and snapshots
OpenClaw = connectivity
```

---

## 22. Codex Task Checklist

When Codex implements the next PR after this documentation PR, it must:

```text
[ ] Inspect current AIVAN GLTG client and facade.
[ ] Add GLTG_API_VERSION config.
[ ] Add v2 request/response DTOs.
[ ] Add v2 request builder from BuyerRequirement / GiraffeContext.
[ ] Add optional behavior feature input mapping.
[ ] Add v2 response parser and mapping into existing DTOs.
[ ] Preserve v1 endpoints and tests.
[ ] Add mock GLTG v2 tests.
[ ] Ensure no local lead-time math is added.
[ ] Ensure GLTG failures remain structured errors.
[ ] Add fixtures for shared cross-repo contract.
[ ] Document porting instructions for abcdYi and giraffe-agent.
[ ] Run test suite.
[ ] Update README or docs only where necessary.
```

---

## 23. PR Description Template for Implementation PR

Use this template for the actual implementation PR:

```md
## Summary

Implements GLTG v2 behavior-aware probabilistic lead-time client contract in AIVAN.

## What changed

- Added GLTG v2 request/response schemas.
- Added GLTG_API_VERSION.
- Added behavior feature payload mapping.
- Added source observation ID propagation.
- Added v2 response mapping for P50/P80/P90, buffers, risk, and explanation.
- Preserved v1 compatibility.

## Boundary

AIVAN still does not calculate lead time locally.
GLTG remains the simulation source.
giraffe-db remains the business fact source.

## Tests

- test_gltg_client_v2.py
- test_gltg_payload_behavior_features.py
- test_gltg_response_mapping_v2.py
- existing v1 regression tests

## Known limitations

- Requires standalone GLTG service v2 endpoint for production.
- giraffe-db behavior snapshot read integration may be feature-flagged until APIs are deployed.

## Next steps

- Implement /v2/lead-time/simulate in GLTG service.
- Port contract to abcdYi and giraffe-agent.
```

---

## 24. Final Product Principle

GLTG must not answer only:

```text
How many days?
```

It must answer:

```text
How many days at P50 / P80 / P90?
Why?
Which buyer/supplier behavior changed the forecast?
How confident are we?
Do we need a fallback supplier?
Do we need manual review?
Should pricing add risk buffer?
```

This is the difference between a simple lead-time calculator and a Giraffe-grade procurement intelligence model.
