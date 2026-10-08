# GLTG Trade and Processing Technical Specification

Reconciled: 2026-10-02. This technical appendix preserves the supplied 2026-06-30 v1.0 factor model's non-conflicting stage topology, factor taxonomy, fifteen formula groups, enums, field mappings, request/response extension shapes, explanation semantics and test scenarios. Read it together with [the integration PRD](GLTG_BEHAVIORAL_STATISTICAL_MODEL_ITERATION_PRD.md). This is a requirements specification, not an implementation claim.

## Applicability and source resolutions

- GLTG is invoked through an API; Aivan does not duplicate the calculation engine. DB facts/process state come from giraffe-db or a compatible hot-swapped user private DB.
- Standard-English workflow/storage rules apply; examples are illustrative model values, not observed supplier facts. Source references remain linked to the actual selected DB evidence.
- The two designated simulated DBs are valid test/acceptance data sources. Use the provider/dataset selected for the delivery and execute actual code/APIs.
- Preserve all factor dimensions below. Do not replace the model with a single supplier-risk score or make slow reply automatically high risk.
- Staged sums and rule-based inference are valid first implementations. Full DAG simulation, optional dedicated observation tables and later statistical/ML calibration are not mandatory prerequisites for that iteration.
- Resolve two source issues explicitly in executable implementation: uncertainty coefficients sum to 1.10; stage/component ownership risks duplicate counting (notably subprocess and buyer/clarification time). Do not silently choose new business parameters or discard factors.
- Inputs with zero/missing denominators, capacity or baselines require explicit validated handling and tests; no fabricated finite commitment. Probability/risk bounds and units must remain documented.
- An equation written here is not implemented merely because it is documented. Declared implemented scope must execute formulas and pass the source scenario/formula/client tests.

The original section numbers are retained below so the source map remains usable.

## 4. End-to-End Lead-Time Framework

GLTG must model total planning lead time as a staged directed graph, not a flat sum.

### 4.1 Canonical time stages

```text
T_total =
  T_requirement_confirmation
+ T_supplier_discovery
+ T_supplier_response
+ T_quote_confirmation
+ T_material_availability
+ T_material_procurement
+ T_preproduction
+ T_capacity_queue
+ T_production
+ T_subprocess
+ T_qc
+ T_rework
+ T_packaging
+ T_export_preparation
+ T_inland_origin
+ T_main_freight
+ T_import_clearance
+ T_inland_destination
+ T_buyer_decision
+ T_risk_buffer
```

But not all stages are strictly sequential. Some may run in parallel.

Therefore GLTG must support a graph formulation:

```text
G = (V, E)

Each node v ∈ V is a time component:
  material confirmation
  material procurement
  sample approval
  production
  QC
  logistics booking
  export customs
  etc.

Each edge e ∈ E is a dependency:
  production cannot start before material arrives
  mass production cannot start before sample approval
  shipping cannot start before packaging and export documents
```

For each path:

```text
T_path = Σ duration(v) for v in critical path
```

Overall lead time:

```text
T_total = max(T_path_1, T_path_2, ..., T_path_k) + buffers
```

MVP can approximate this with staged sums, but the model must be designed for future DAG simulation.

---

## 5. Time-Impact Factor Taxonomy

## 5.1 Buyer / Requirement Factors

| Factor | Variable | Effect |
|---|---|---|
| Requirement completeness | `requirement_completeness_score` | Lower score increases clarification delay |
| Requirement volatility | `requirement_volatility_score` | Increases buyer decision buffer and rework risk |
| Target delivery strictness | `deadline_strictness_score` | Changes confidence level recommendation |
| Buyer decision speed | `buyer_decision_delay_score` | Adds confirmation delay |
| Sample approval delay | `sample_approval_delay_score` | Adds pre-production delay |
| Payment / deposit delay | `payment_delay_risk` | Delays production start |
| Packaging / labeling uncertainty | `packaging_uncertainty_score` | Adds packaging/pre-production delay |
| QC requirement level | `quality_requirement_level` | Adds QC and potential rework time |
| Certification requirement | `certification_requirement_score` | Adds lab/test/certification delay |

## 5.2 Supplier Execution Factors

| Factor | Variable | Effect |
|---|---|---|
| Execution mode | `supplier_execution_mode` | Determines control risk |
| In-house capability confidence | `in_house_capability_confidence` | Higher confidence lowers upstream risk |
| Outsourcing dependency | `upstream_dependency_probability` | Widens P80/P90 |
| Supplier current load | `supplier_current_load_signal` | Adds queue and uncertainty |
| Capacity utilization | `capacity_utilization_ratio` | Adds queue delay nonlinearly |
| Effective capacity | `effective_daily_capacity` | Determines production time |
| Historical on-time rate | `historical_on_time_delivery_rate` | Adjusts risk |
| Historical quote revision rate | `quote_revision_rate` | Adjusts quote confidence |
| Historical quoted-vs-actual error | `historical_quoted_vs_actual_error_days` | Adjusts uncertainty |

## 5.3 Raw Material / Inventory Factors

| Factor | Variable | Effect |
|---|---|---|
| Material availability status | `material_availability_status` | Determines material procurement time |
| Stock coverage ratio | `stock_coverage_ratio` | Partial stock causes split/uncertainty |
| Material availability confidence | `material_availability_confidence` | Controls tail risk |
| Material supplier confirmation probability | `raw_material_supplier_confirmation_probability` | Indicates upstream material dependency |
| Raw material lead time estimate | `raw_material_lead_time_estimate_days` | Adds material procurement time |
| Raw material lead time uncertainty | `raw_material_lead_time_uncertainty_score` | Widens P80/P90 |
| Substitute material probability | `substitute_material_probability` | Adds buyer approval + QC risk |
| Material lock required | `material_lock_required` | Adds commercial decision pressure |
| Material lock validity | `material_lock_validity_days` | Affects quote validity and risk of price/lead-time drift |

Material availability status enum:

```text
in_stock
reserved_stock
partial_stock
supplier_confirmation_required
not_available
substitute_material_required
unknown
```

## 5.4 Manufacturing / Processing Factors

| Factor | Variable | Effect |
|---|---|---|
| Process complexity | `process_complexity_score` | Multiplies production time |
| Customization level | `customization_level_score` | Adds pre-production and setup |
| Tooling / mold / pattern requirement | `tooling_required` / `tooling_days` | Adds pre-production |
| Sample requirement | `sample_required` / `sample_days` | Adds approval delay |
| Lab dip / color approval | `color_approval_required` / `color_approval_days` | Adds pre-production |
| Printing / embroidery / washing | `subprocess_days` | Adds subprocess time |
| External subcontract process | `external_subprocess_dependency_score` | Adds uncertainty |
| Setup/changeover time | `setup_days` | Adds production preparation |
| Yield / defect rate | `expected_yield_rate` | Adjusts effective capacity and rework |
| QC intensity | `qc_intensity_score` | Adds QC time |
| Rework probability | `rework_probability` | Adds expected rework buffer |

## 5.5 Logistics / Trade Factors

| Factor | Variable | Effect |
|---|---|---|
| Incoterms | `incoterms` | Determines responsibility and included logistics stages |
| Logistics mode | `logistics_mode` | Determines base freight time |
| Route baseline | `route_baseline_days` | Base logistics duration |
| Container / cargo space availability | `freight_space_risk` | Adds shipping wait |
| Sailing / flight frequency | `departure_frequency_days` | Adds wait time |
| Export documentation readiness | `export_doc_readiness_score` | Adds export prep risk |
| Customs inspection risk | `customs_inspection_probability` | Adds tail risk |
| Origin inland transport | `origin_inland_days` | Adds origin transport |
| Destination inland transport | `destination_inland_days` | Adds final delivery |
| Holiday / peak season | `calendar_disruption_score` | Adds queue/logistics risk |
| Port congestion / weather / disruption | `logistics_disruption_score` | Adds tail risk |
| Trade compliance restriction | `trade_compliance_risk` | Adds manual review and delay risk |

## 5.6 Communication / Behavior Factors

| Factor | Variable | Effect |
|---|---|---|
| Supplier response delay ratio | `supplier_response_delay_ratio` | Behavior signal, not direct risk |
| Business-hours delay ratio | `business_hours_delay_ratio` | More meaningful than natural time |
| Quote completeness | `quote_completeness_score` | Low score increases uncertainty |
| Missing lead time | `missing_lead_time` | Major uncertainty signal |
| Missing material status | `missing_material_status` | Major material risk signal |
| Price revision count | `price_revision_count` | Price confidence risk |
| Lead-time revision count | `lead_time_revision_count` | Lead-time confidence risk |
| Upstream confirmation signal | `upstream_confirmation_signal` | Indicates dependency |
| Low engagement probability | `low_engagement_probability` | Adds median delay and fallback risk |
| Careful quotation probability | `careful_quotation_probability` | May reduce quote-quality risk |
| Timezone / holiday explanation | `calendar_explanation_probability` | Should not be over-penalized |

---

## 6. Key Variable Formulas

## 6.1 Requirement completeness

```text
requirement_completeness_score =
  completed_required_fields / total_required_fields
```

Required fields should be category-specific. For apparel/textile:

```text
product type
quantity
material
color
size/spec
destination
target delivery date or target days
quality requirement
packaging requirement
incoterms if known
```

Clarification delay:

```text
T_requirement_confirmation =
  base_clarification_days * (1 - requirement_completeness_score)
+ buyer_decision_delay_days
```

---

## 6.2 Stock coverage ratio

```text
stock_coverage_ratio =
  available_material_qty / required_material_qty
```

Interpretation:

```text
stock_coverage_ratio >= 1.0
  → material_availability_status = in_stock or reserved_stock

0 < stock_coverage_ratio < 1.0
  → material_availability_status = partial_stock

stock_coverage_ratio = 0 or unknown + supplier confirmation needed
  → material_availability_status = supplier_confirmation_required or unknown
```

Material procurement days:

```text
T_material_procurement =
  0                                             if in_stock
  lock_confirmation_days                        if reserved_stock
  partial_shortage_procurement_days             if partial_stock
  raw_material_lead_time_estimate_days          if supplier_confirmation_required
  substitute_material_approval_days + material_procurement_days if substitute_material_required
  default_category_material_days * uncertainty_multiplier if unknown
```

---

## 6.3 Material availability risk

```text
material_availability_risk =
  w1 * status_risk(material_availability_status)
+ w2 * (1 - material_availability_confidence)
+ w3 * raw_material_supplier_confirmation_probability
+ w4 * raw_material_lead_time_uncertainty_score
+ w5 * substitute_material_probability
+ w6 * historical_material_delay_rate
```

Initial weights:

```text
w1 = 0.25
w2 = 0.20
w3 = 0.20
w4 = 0.15
w5 = 0.10
w6 = 0.10
```

Status risk mapping:

```text
in_stock = 0.05
reserved_stock = 0.10
partial_stock = 0.45
supplier_confirmation_required = 0.65
not_available = 0.90
substitute_material_required = 0.85
unknown = 0.70
```

---

## 6.4 Supplier execution control score

```text
execution_control_score =
  0.35 * in_house_capability_confidence
+ 0.20 * historical_on_time_delivery_rate
+ 0.15 * quote_completeness_score
+ 0.15 * material_availability_confidence
+ 0.15 * (1 - upstream_dependency_probability)
```

Interpretation:

```text
0.80 - 1.00 = high control
0.60 - 0.80 = medium-high control
0.40 - 0.60 = medium control
0.20 - 0.40 = low control
0.00 - 0.20 = very low control
```

---

## 6.5 Upstream dependency probability

```text
upstream_dependency_probability =
  0.25 * explicit_upstream_signal
+ 0.20 * raw_material_supplier_confirmation_probability
+ 0.15 * missing_material_status
+ 0.10 * supplier_company_type_trader_score
+ 0.10 * external_subprocess_dependency_score
+ 0.10 * quote_revision_frequency_score
+ 0.05 * response_delay_ratio_score
+ 0.05 * historical_leadtime_error_score
```

Important rule:

```text
Response delay is only one weak input.
Explicit material/upstream signals and missing material status are stronger signals.
```

---

## 6.6 Supplier response delay ratio

```text
supplier_response_delay_ratio =
  current_case_supplier_response_seconds / supplier_historical_response_seconds
```

Fallback hierarchy if supplier history is missing:

```text
supplier historical baseline
→ buyer-supplier pair baseline
→ category supplier baseline
→ tenant baseline
→ global default
```

Business-hours delay ratio:

```text
business_hours_delay_ratio =
  current_case_business_hours_response_seconds / historical_business_hours_response_seconds
```

---

## 6.7 Response delay reason inference

Do not treat slow response as one direct risk. Infer the likely reason.

Candidate reasons:

```text
material_inventory_check
raw_material_supplier_confirmation
capacity_check
subsupplier_process_confirmation
low_engagement
careful_quotation
timezone_or_holiday
unknown
```

Rule-based MVP scoring:

```text
score(material_inventory_check) =
  0.35 * material_keywords
+ 0.25 * missing_material_status
+ 0.20 * response_delay_ratio_score
+ 0.20 * in_house_capability_confidence

score(raw_material_supplier_confirmation) =
  0.40 * explicit_material_supplier_signal
+ 0.20 * raw_material_supplier_confirmation_probability
+ 0.15 * missing_material_status
+ 0.15 * supplier_response_delay_ratio_score
+ 0.10 * historical_material_delay_rate

score(capacity_check) =
  0.35 * capacity_keywords
+ 0.25 * capacity_utilization_ratio
+ 0.20 * production_schedule_keywords
+ 0.20 * in_house_capability_confidence

score(low_engagement) =
  0.30 * response_delay_ratio_score
+ 0.20 * incomplete_quote_score
+ 0.20 * no_response_history_score
+ 0.15 * low_relationship_strength_score
+ 0.15 * no_clear_reason_signal

score(careful_quotation) =
  0.30 * complete_quote_score
+ 0.25 * detailed_breakdown_signal
+ 0.20 * explicit_checking_signal
+ 0.15 * historical_quote_accuracy_score
+ 0.10 * in_house_capability_confidence

score(timezone_or_holiday) =
  0.50 * non_working_time_overlap
+ 0.30 * holiday_calendar_match
+ 0.20 * normal_business_hours_response
```

Convert scores to probabilities:

```text
P(reason_i) = exp(score_i) / Σ exp(score_j)
```

Primary reason:

```text
most_likely_response_delay_reason = argmax P(reason_i)
```

---

## 6.8 Effective daily capacity

**Accounting issue retained for implementation resolution:** the source's production formula below includes `subprocess_days`, while sections 4 and 11 also list subprocess separately. Preserve the factor but assign it to one non-overlapping component before executing the total; test that it is counted exactly once. The same ownership rule applies to overlapping clarification/buyer-decision components. No equation is silently changed here.


```text
effective_daily_capacity =
  nominal_daily_capacity
* capacity_availability_factor
* expected_yield_rate
* priority_factor
* process_efficiency_factor
```

Where:

```text
capacity_availability_factor = max(0, 1 - capacity_utilization_ratio)
priority_factor = 1.0 for normal, >1 for prioritized, <1 for low-priority
process_efficiency_factor = 1 / process_complexity_multiplier
```

Production days:

```text
T_production =
  setup_days
+ ceil(order_quantity / effective_daily_capacity)
+ subprocess_days
```

If effective capacity is missing:

```text
T_production =
  category_default_production_days
* quantity_band_multiplier
* process_complexity_multiplier
```

---

## 6.9 Capacity queue risk

Capacity utilization is nonlinear.

```text
capacity_queue_risk =
  0                                if utilization <= 0.70
  (utilization - 0.70) / 0.20       if 0.70 < utilization <= 0.90
  1.0                              if utilization > 0.90
```

Queue days:

```text
T_capacity_queue =
  base_queue_days * capacity_queue_risk * priority_adjustment
```

---

## 6.10 Process complexity multiplier

```text
process_complexity_multiplier =
  1
+ 0.15 * customization_level_score
+ 0.10 * quality_requirement_level_score
+ 0.10 * packaging_complexity_score
+ 0.15 * external_subprocess_dependency_score
+ 0.10 * tooling_required_flag
+ 0.10 * color_approval_required_flag
```

Clip:

```text
1.0 <= process_complexity_multiplier <= 2.0
```

---

## 6.11 Rework expected days

```text
expected_rework_days =
  rework_probability * rework_days_if_triggered
```

Rework probability:

```text
rework_probability =
  base_category_defect_rate
+ 0.10 * quality_requirement_level_score
+ 0.10 * new_supplier_flag
+ 0.10 * material_substitution_flag
+ 0.05 * rushed_order_flag
- 0.10 * historical_quality_score
```

Clip to `[0, 1]`.

---

## 6.12 Logistics wait time

Departure wait time:

```text
T_departure_wait =
  departure_frequency_days / 2
```

If booking is not confirmed:

```text
T_departure_wait =
  departure_frequency_days / 2
+ freight_space_risk * departure_frequency_days
```

Total logistics:

```text
T_logistics =
  origin_inland_days
+ export_preparation_days
+ departure_wait_days
+ main_freight_days
+ import_clearance_days
+ destination_inland_days
+ logistics_disruption_buffer_days
```

---

## 6.13 Customs / compliance risk buffer

```text
customs_risk_buffer_days =
  customs_inspection_probability * expected_customs_delay_days
+ trade_compliance_risk * manual_review_delay_days
```

If `trade_compliance_risk >= 0.7`:

```text
manual_review_required = true
```

---

## 6.14 Buyer delay buffer

```text
T_buyer_decision =
  buyer_decision_delay_score * historical_avg_buyer_decision_days
+ requirement_volatility_score * requirement_change_buffer_days
+ sample_approval_delay_score * sample_approval_days
+ payment_delay_risk * payment_start_delay_days
```

---

## 6.15 Quote confidence score

Fast response does not always mean high confidence.

```text
quote_confidence_score =
  0.25 * quote_completeness_score
+ 0.20 * material_availability_confidence
+ 0.15 * lead_time_confidence_score
+ 0.15 * historical_quote_accuracy_score
+ 0.10 * execution_control_score
+ 0.10 * source_evidence_score
+ 0.05 * detailed_breakdown_signal
```

Penalty:

```text
if supplier_response_fast
and material_availability_status in {unknown, supplier_confirmation_required}
and supplier_stated_lead_time_days is precise
and no supporting evidence:
  quote_confidence_score -= 0.15
```

This captures:

```text
Fast response + unsupported material/lead-time commitment may be low-quality quotation.
```

---

## 7. Lead-Time Distribution Composer

GLTG must output:

```text
P50
P80
P90
components
risk decomposition
explanation
```

## 7.1 Base stage durations

For each stage:

```text
stage_duration = deterministic_component + expected_delay_component
```

Example:

```text
T_base =
  T_requirement_confirmation
+ T_material_procurement
+ T_preproduction
+ T_capacity_queue
+ T_production
+ T_qc
+ T_packaging
+ T_logistics
+ T_buyer_decision
```

## 7.2 Risk decomposition

**Coefficient issue retained for implementation resolution:** the source coefficients below total 1.10. Declare and test the selected normalization/bounds convention before claiming implementation. They are preserved as source parameters, not silently treated as a validated unit-sum risk score.


Separate risk dimensions:

```text
engagement_risk
execution_control_risk
upstream_dependency_risk
material_availability_risk
capacity_risk
process_complexity_risk
quality_rework_risk
logistics_risk
customs_compliance_risk
buyer_delay_risk
lead_time_uncertainty_risk
```

Total uncertainty score:

```text
lead_time_uncertainty_risk =
  0.18 * material_availability_risk
+ 0.16 * upstream_dependency_risk
+ 0.14 * execution_control_risk
+ 0.12 * capacity_risk
+ 0.10 * process_complexity_risk
+ 0.10 * quality_rework_risk
+ 0.10 * logistics_risk
+ 0.08 * customs_compliance_risk
+ 0.07 * buyer_delay_risk
+ 0.05 * quote_confidence_penalty
```

## 7.3 Quantile spread

MVP formula:

```text
P50 = T_base + central_shift_days

P80 = P50 + base_spread_days * (1 + 0.8 * lead_time_uncertainty_risk)

P90 = P50 + base_spread_days * (1 + 1.3 * lead_time_uncertainty_risk)
```

Alternative pseudo-lognormal formula:

```text
μ = log(P50_base)
σ = (log(P90_base) - log(P50_base)) / 1.2816

μ* = μ + Δμ
σ* = clip(σ * exp(Δσ), σ_min, σ_max)

P50 = exp(μ*)
P80 = exp(μ* + σ* * 0.8416)
P90 = exp(μ* + σ* * 1.2816)
```

Mapping:

```text
low_engagement_probability
  → increases Δμ and fallback risk

material_availability_risk
  → increases Δσ and material buffer

upstream_dependency_probability
  → increases Δσ more than Δμ

capacity_utilization_ratio
  → increases both Δμ and Δσ when high

logistics_disruption_score
  → increases Δσ mostly

buyer_decision_delay_score
  → increases Δμ
```

---

## 8. Specific Inventory/Response-Speed Logic

The model must explicitly handle these cases.

### 8.1 Factory has raw material inventory

```text
material_availability_status = in_stock
supplier_response_speed = fast or normal
```

Interpretation:

```text
Supplier can quote independently.
Material procurement risk is low.
Lead-time confidence increases if quote is complete.
```

Adjustment:

```text
T_material_procurement = 0
material_availability_risk <= 0.10
quote_confidence_score +0.05
P80/P90 spread narrows
```

### 8.2 Factory lacks raw material inventory and must confirm with material supplier

```text
material_availability_status = supplier_confirmation_required
supplier_response_speed = slow
```

Interpretation:

```text
Slow response is not necessarily low engagement.
It may indicate material supplier confirmation.
Execution ability may still be high if factory is in-house capable.
```

Adjustment:

```text
low_engagement_probability should not automatically increase.
raw_material_supplier_confirmation_probability increases.
material_availability_risk increases.
execution_control_score may remain medium/high.
P50 increases moderately.
P80/P90 widen materially.
```

### 8.3 Factory lacks inventory but responds too fast with unsupported certainty

```text
material_availability_status = unknown or supplier_confirmation_required
supplier_response_speed = fast
quote gives precise lead time
no material evidence
```

Interpretation:

```text
Fast response may be a low-quality or unverified quotation.
```

Adjustment:

```text
quote_confidence_score decreases.
manual_review_required may be true if deadline is tight.
lead_time_uncertainty_risk increases.
```

### 8.4 Trader/broker needs factory and material confirmation

```text
supplier_execution_mode = trader / broker
material_availability_status = supplier_confirmation_required
upstream_dependency_probability high
```

Interpretation:

```text
Multiple layers of upstream dependency.
Execution control is lower.
Tail risk is high.
```

Adjustment:

```text
execution_control_score decreases.
upstream_dependency_risk increases.
material_availability_risk increases.
fallback_supplier_required = true if deadline strict.
P80/P90 widen strongly.
```

---

## 9. DB Feature Mapping

Implement the calculations in the standalone GLTG API dependency. Map these field semantics to the chosen private-domain DB provider. The giraffe-db table/column names below are a reference mapping, not a requirement to use one physical schema or instance.

## 9.1 `behavior_observations.behavior_type` additions

Add or support these behavior types:

```text
material_in_stock_signal
material_reserved_signal
partial_material_stock_signal
material_supplier_confirmation_required
material_availability_pending
material_not_available_signal
substitute_material_required
raw_material_lead_time_signal
capacity_check_signal
production_schedule_check_signal
careful_quotation_signal
low_quality_fast_quote_signal
unsupported_precise_leadtime_signal
subsupplier_process_confirmation_required
```

## 9.2 `supplier_behavior_feature_snapshots.feature_json` additions

Support:

```json
{
  "supplier_execution_mode": "in_house_manufacturer",
  "in_house_capability_confidence": 0.82,
  "upstream_dependency_probability": 0.35,
  "execution_control_score": 0.74,

  "material_availability_status": "supplier_confirmation_required",
  "material_availability_confidence": 0.35,
  "stock_coverage_ratio": 0.0,
  "raw_material_inventory_signal": 0.22,
  "raw_material_supplier_confirmation_probability": 0.75,
  "raw_material_lead_time_estimate_days": 5,
  "raw_material_lead_time_uncertainty_score": 0.68,
  "substitute_material_probability": 0.12,
  "material_lock_required": true,
  "material_lock_validity_days": 3,

  "response_delay_reason_inference": {
    "most_likely_reason": "raw_material_supplier_confirmation",
    "confidence": 0.68,
    "probabilities": {
      "raw_material_supplier_confirmation": 0.68,
      "capacity_check": 0.14,
      "careful_quotation": 0.10,
      "low_engagement": 0.05,
      "timezone_or_holiday": 0.03
    }
  }
}
```

## 9.3 `gltg_behavior_inputs.feature_json` additions

Support:

```json
{
  "supplier_response_delay_ratio": 3.0,
  "business_hours_delay_ratio": 2.5,
  "material_availability_status": "supplier_confirmation_required",
  "material_availability_risk": 0.72,
  "upstream_dependency_probability": 0.75,
  "execution_control_score": 0.66,
  "quote_confidence_score": 0.58,
  "lead_time_uncertainty_risk": 0.74,
  "most_likely_response_delay_reason": "raw_material_supplier_confirmation"
}
```

## 9.4 Optional new table: `material_availability_observations`

If the current `behavior_observations` model becomes too overloaded, add a dedicated table.

Fields:

```text
material_availability_observation_id
tenant_id

procurement_case_id
rfq_id nullable
quote_id nullable
supplier_id
product_category_id nullable
product_id nullable
rfq_line_item_id nullable
quote_line_item_id nullable

material_name nullable
material_spec_json
required_material_qty nullable
available_material_qty nullable
stock_coverage_ratio nullable

material_availability_status
material_availability_confidence

raw_material_supplier_id nullable
raw_material_supplier_known boolean
raw_material_supplier_confirmation_required boolean
raw_material_lead_time_estimate_days nullable
raw_material_lead_time_uncertainty_score nullable

substitute_material_required boolean
substitute_material_probability nullable
substitute_material_approval_required boolean

source_event_id nullable
source_quote_line_item_id nullable

verification_status
confidence
confirmed_by nullable
confirmed_at nullable

created_at
updated_at
metadata_json
```

Implementation rule:

```text
This table is optional. Add equivalent dedicated storage only when the existing extensible observations cannot represent the selected requirements; preserve the compatible provider contract.
If added, add API, seed data, tests, and lineage.
```

---

## 10. GLTG v2 Request Schema Extension

Extend the current GLTG v2 request with:

```json
{
  "trade_processing_factors": {
    "requirement": {
      "requirement_completeness_score": 0.78,
      "requirement_volatility_score": 0.30,
      "deadline_strictness_score": 0.80,
      "quality_requirement_level_score": 0.50,
      "packaging_complexity_score": 0.25
    },
    "supplier_execution": {
      "supplier_execution_mode": "in_house_manufacturer",
      "in_house_capability_confidence": 0.82,
      "upstream_dependency_probability": 0.35,
      "execution_control_score": 0.74,
      "capacity_utilization_ratio": 0.72,
      "nominal_daily_capacity": 500,
      "effective_daily_capacity": 390
    },
    "material": {
      "material_availability_status": "supplier_confirmation_required",
      "stock_coverage_ratio": 0.0,
      "material_availability_confidence": 0.35,
      "raw_material_supplier_confirmation_probability": 0.75,
      "raw_material_lead_time_estimate_days": 5,
      "raw_material_lead_time_uncertainty_score": 0.68,
      "substitute_material_probability": 0.12,
      "material_lock_required": true,
      "material_lock_validity_days": 3
    },
    "processing": {
      "process_complexity_score": 0.45,
      "customization_level_score": 0.40,
      "tooling_required": false,
      "sample_required": true,
      "sample_days": 3,
      "color_approval_required": false,
      "external_subprocess_dependency_score": 0.20,
      "expected_yield_rate": 0.95,
      "rework_probability": 0.08
    },
    "logistics_trade": {
      "incoterms": "FOB",
      "logistics_mode": "sea",
      "route_baseline_days": 18,
      "departure_frequency_days": 7,
      "freight_space_risk": 0.20,
      "customs_inspection_probability": 0.10,
      "trade_compliance_risk": 0.05,
      "calendar_disruption_score": 0.20,
      "logistics_disruption_score": 0.15
    },
    "behavior": {
      "supplier_response_delay_ratio": 3.0,
      "business_hours_delay_ratio": 2.5,
      "quote_completeness_score": 0.65,
      "quote_confidence_score": 0.58,
      "most_likely_response_delay_reason": "raw_material_supplier_confirmation",
      "low_engagement_probability": 0.05,
      "careful_quotation_probability": 0.10
    }
  }
}
```

---

## 11. GLTG v2 Response Schema Extension

Extend GLTG response with detailed components:

```json
{
  "components": {
    "requirement_confirmation_days": 1,
    "supplier_response_buffer_days": 1,
    "material_confirmation_days": 2,
    "material_procurement_days": 5,
    "preproduction_days": 3,
    "capacity_queue_days": 2,
    "production_days": 26,
    "subprocess_days": 0,
    "qc_days": 2,
    "expected_rework_days": 1,
    "packaging_days": 1,
    "export_preparation_days": 1,
    "origin_inland_days": 1,
    "departure_wait_days": 3,
    "main_freight_days": 18,
    "import_clearance_days": 2,
    "destination_inland_days": 2,
    "buyer_decision_buffer_days": 2,
    "risk_buffer_days": 4
  },
  "risk_decomposition": {
    "engagement_risk": 0.10,
    "execution_control_risk": 0.28,
    "upstream_dependency_risk": 0.62,
    "material_availability_risk": 0.72,
    "capacity_risk": 0.35,
    "process_complexity_risk": 0.22,
    "quality_rework_risk": 0.18,
    "logistics_risk": 0.20,
    "customs_compliance_risk": 0.08,
    "buyer_delay_risk": 0.30,
    "lead_time_uncertainty_risk": 0.61
  },
  "response_delay_reason_inference": {
    "most_likely_reason": "raw_material_supplier_confirmation",
    "confidence": 0.68,
    "probabilities": {
      "raw_material_supplier_confirmation": 0.68,
      "capacity_check": 0.14,
      "careful_quotation": 0.10,
      "low_engagement": 0.05,
      "timezone_or_holiday": 0.03
    }
  },
  "quantiles": {
    "p50_days": 43,
    "p80_days": 55,
    "p90_days": 64
  },
  "explanation_json": {
    "summary": "Supplier response is slow, but the primary inferred reason is raw material supplier confirmation rather than low engagement. Median lead time is moderately increased, while P80/P90 are widened due to material availability uncertainty.",
    "adjustments": []
  }
}
```

---

## 12. Explanation Requirements

Every GLTG response must explain:

```text
which factors increased P50
which factors widened P80/P90
whether supplier delay was classified as low engagement, material confirmation, capacity check, careful quotation, or timezone/holiday
whether material was in stock, partially available, pending supplier confirmation, or unknown
whether supplier execution control is high or low
which observations and feature snapshots supported the conclusion
```

Example explanation:

```text
Supplier response is 3.0x slower than historical baseline. The model does not classify this as low engagement because the supplier message indicates fabric mill confirmation and the supplier has in-house production capability. GLTG classifies the delay as likely raw material supplier confirmation. P50 is increased by 2 days for material confirmation, while P80/P90 are widened due to material availability uncertainty.
```

---

## 13. Required Tests

## 13.1 Inventory / response-speed scenario tests

### Test A — Fast response + material in stock

Expected:

```text
material_availability_risk low
quote_confidence_score high
P80/P90 spread narrow
no fallback supplier required
```

### Test B — Slow response + factory + material supplier confirmation

Expected:

```text
low_engagement_probability remains low
raw_material_supplier_confirmation_probability high
material_availability_risk high
execution_control_score remains medium/high
P50 moderately increases
P80/P90 widen materially
```

### Test C — Fast response + no material evidence + precise lead time

Expected:

```text
quote_confidence_score decreases
unsupported_precise_leadtime_signal generated
manual_review_required if deadline strict
```

### Test D — Trader + material pending

Expected:

```text
upstream_dependency_probability high
execution_control_score low/medium
P80/P90 widen strongly
fallback_supplier_required if deadline strict
```

## 13.2 Formula tests

Test deterministic outputs for:

```text
stock_coverage_ratio
material_availability_risk
execution_control_score
upstream_dependency_probability
response_delay_reason_inference
effective_daily_capacity
production_days
capacity_queue_risk
process_complexity_multiplier
quote_confidence_score
lead_time_uncertainty_risk
P50/P80/P90 monotonicity
```

## 13.3 Regression tests

Existing AIVAN/GLTG client tests must still pass.

---
