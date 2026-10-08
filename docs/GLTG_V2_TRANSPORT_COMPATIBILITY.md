# Existing GLTG v2 Transport Compatibility Reference

Source snapshot: Aivan `6ee2d3cf2e79df2d472149db18a08e289882cb56`, previous GLTG iteration document section 12. Preserved during the 2026-10-02 cleanup so existing endpoint/field compatibility is not lost. It is not an independent source of broader product scope or a claim that all endpoints are deployed.

The current [integration PRD](GLTG_BEHAVIORAL_STATISTICAL_MODEL_ITERATION_PRD.md) and [trade-processing technical specification](GLTG_TRADE_PROCESSING_TECHNICAL_SPEC.md) define the source-aligned target and additive factor extensions. Preserve existing consumers' supported contract, field names, v1 mapping and explicit error behavior while evolving it. A particular physical DB instance is not required.

Treat unknown/missing inputs, unsupported versions, authentication/tenant errors, non-success status, invalid response and transport timeout as explicit failures in the selected API contract, not invented quantiles or a silent local engine. The exact stable error identifiers remain those of the selected version; this appendix does not invent a new endpoint or code. Legacy model-method/rule examples in the response identify metadata, not a requirement for a specific learning algorithm or long-term calibration before rule-based delivery.

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
