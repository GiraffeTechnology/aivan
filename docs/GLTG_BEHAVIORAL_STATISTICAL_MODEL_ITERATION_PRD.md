# GLTG Trade and Processing Time Integration Requirements

Reconciled: 2026-10-02. Source: the supplied GLTG Trade & Processing Time Factor Model Iteration v1.0 of 2026-06-30, as mapped in [source reconciliation](PRODUCT_SOURCE_RECONCILIATION.md). This is the dependency iteration consumed by Aivan, not a replacement product definition or evidence that the model is implemented.

## Technical specification and compatibility

The [trade-processing technical specification](GLTG_TRADE_PROCESSING_TECHNICAL_SPEC.md) is part of this iteration's requirements: it preserves the full source taxonomy, fifteen formula groups, stage topology, enums, field mappings, request/response shapes, explanations and scenario/formula tests. The [existing v2 transport reference](GLTG_V2_TRANSPORT_COMPATIBILITY.md) preserves current client field/endpoint and v1 compatibility context. This overview does not replace those details.

## 1. Boundary and outcome

GLTG is an API-invoked lead-time/feasibility dependency. Aivan, abcdYi and Giraffe Agent are consumers. The private-domain DB supplies business history, observations, features and process state through a replaceable provider boundary. GPM provides quotation/pricing guidance through its actual API contract. Aivan must not implement a hidden local GLTG or replace failed GLTG responses with LLM-invented lead times.

The user should see P50/P80/P90 where supported, why the estimate changed, material and upstream uncertainty, and useful actions. A slow supplier response is a behavioral signal, not a direct high-risk verdict. A fast reply is not evidence that the quotation is reliable.

## 2. Inputs

The factor contract separates:

| Group | Required semantics for the selected calculation |
| --- | --- |
| Requirement/buyer | Completeness, volatility, deadline strictness, decision/sample/payment delay, packaging, quality and certification needs |
| Supplier execution | In-house versus upstream execution, capability confidence, capacity/utilization, current load, historical on-time/quote-error evidence |
| Material | Availability status, stock coverage, confidence, confirmation probability, procurement time/uncertainty, substitutions and lock validity |
| Processing | Quantity, setup, complexity/customization, tooling, samples/color approval, subprocess dependencies, yield, QC and rework |
| Logistics/trade | Incoterms, mode/route, space and departure frequency, documents, customs, inland legs, calendar/disruption signals |
| Communication | Response delay relative to a justified baseline, business-hours delay, quote completeness/revisions, explicit checking signals and reason inference |

Keep observed facts, unknowns, estimates and inferred probabilities distinct. Retain source observation/feature references, feature window and applicable model/rule versions. Preserve supplier-provided quotation fields; do not overwrite them with inferred confidence or calculated lead time. Standard-English workflow and DB rules apply through [the language boundary](GIRAFFE_INTERNAL_WORKING_LANGUAGE.md).

Material states include in stock, reserved stock, partial stock, supplier confirmation required, unavailable, substitute required and unknown. Required fields may be category-specific; missing facts must be exposed instead of filled by an LLM.

## 3. Calculation semantics

The first iteration may use deterministic/rule-based formulas and staged sums. Design for future dependency-graph simulation without requiring a complete DAG engine before this iteration can be delivered.

The source defines these calculation responsibilities:

- Requirement completeness is completed required fields divided by total applicable required fields; clarification delay depends on missing requirements and buyer response.
- Stock coverage is available material quantity divided by required quantity. Material time depends on the declared stock/confirmation/substitution state.
- Material risk combines status, evidence confidence, upstream confirmation, uncertainty, substitution and historical delay.
- Execution control combines in-house confidence, prior on-time performance, quote completeness, material confidence and upstream dependence.
- Upstream dependence gives explicit material/subsupplier evidence more weight than response delay alone.
- Response-delay ratios use the supplier baseline, then relevant pair/category/tenant/default baselines when necessary; record which baseline was used.
- Rule-based reason inference distinguishes inventory checks, raw-material confirmation, capacity/subsupplier checks, low engagement, careful quotation, calendar effects and unknown cause.
- Effective capacity depends on nominal capacity, availability, yield, priority and process efficiency. Production time accounts for setup, required quantity/effective capacity and subprocess time once.
- Capacity queue risk increases nonlinearly near saturation. Complexity changes processing duration; expected rework depends on rework probability and duration.
- Logistics includes applicable inland, export, departure wait, freight, import and disruption components; buyer delay covers the relevant decision/sample/payment/change effects once.
- Quote confidence reflects completeness, material/lead-time evidence and historical accuracy. An unsupported fast precise promise may reduce confidence rather than improve it.

For the selected implemented composer, quantiles are nonnegative and monotone: P50 <= P80 <= P90. The source's staged MVP and pseudo-lognormal forms are alternatives, not an instruction to add both results. Separate median shift from uncertainty/tail expansion. Explain which factors affect each.

### Technical issues to resolve in implementation

The supplied uncertainty weights total 1.10 without a normalization convention. The source also lists subprocess both inside production and separately, with overlapping buyer/clarification terms. Declare the chosen normalization, duration ownership and units, then cover them with formula/component tests. Do not silently count the same duration twice. Zero/missing effective capacity must have explicit behavior, not division by zero or a fabricated finite promise.

These are bounded technical specification decisions. They do not introduce a new business gate or require customers to approve each coefficient. Initial parameters remain model assumptions, not proven commercial guarantees.

## 4. API and persistence contract

Use the deployed GLTG API version selected by the integration; do not infer compatibility from an HTTP 200 alone. Existing Aivan clients expose v1 estimate/path/reforecast and a v2 simulation/path/reforecast contract. Preserve supported client compatibility while a new contract is introduced, with explicit tests.

For the trade-processing iteration, map the `trade_processing_factors` request groups for requirement, supplier execution, material, processing, logistics/trade and behavior. The response supplies:

- `quantiles` with `p50_days`, `p80_days`, `p90_days`;
- `components` for applicable stages and buffers, with unambiguous inclusion rules;
- `risk_decomposition` keeping engagement, control, upstream, material, capacity, process, rework, logistics/customs, buyer delay and uncertainty distinguishable;
- `response_delay_reason_inference`, with cause probabilities/confidence clearly labeled as inference;
- `explanation_json`, source observation/feature references and applicable run/model/rule metadata.

Map observations and snapshots to the selected private-domain provider. Its physical table names need not match giraffe-db's examples, but the business semantics and evidence must remain usable. New `material_availability_observations` storage is optional if existing extensible observation records suffice. Do not force a new table, a fixed Postgres/MySQL instance or production-customer data to consume the API.

Persist the result and relevant input/evidence references as process data so a later session can reconstruct the decision from DB state. Do not rely on conversation memory. The two designated simulated DBs are valid sources for real API execution and acceptance.

## 5. Explanation and action

Explain why P50 moved, why P80/P90 widened, material status, the reason inferred for response delay, execution-control uncertainty and supporting observations. Aivan can ask whether a supplier manufactures in-house, has stock, must consult an upstream supplier, can lock material, or needs substitution and its price/quality/time effects.

Show real available alternatives and human-review suggestions; never fabricate a fallback supplier to satisfy a Top-3 shape. A risk threshold or model inference is not a final legal/compliance determination or permission to send a commitment.

## 6. Tests and completion

The four source-defined scenario tests are required for the claimed iteration:

| Scenario | Expected behavior |
| --- | --- |
| A: Fast reply and material in stock | Low material risk and narrower tails when evidence/quote completeness support it |
| B: Slow reply from an in-house factory checking material | Increased material/upstream uncertainty without automatically classifying low engagement; median/tail effects remain distinct |
| C: Fast precise promise without material evidence | Reduced quote confidence and appropriate warning/review when the deadline is strict |
| D: Trader/broker with material pending | Upstream dependence and wider tails, with an actual fallback suggestion only when one exists |

Test deterministic factor formulas, missing/zero/boundary inputs, units, no duplicate component time, monotone quantiles, source/provenance mapping and client regressions. Exercise the real selected GLTG and DB API path when claiming integration; label mock tests accurately and do not count skipped CI as executed evidence.

An implemented iteration requires executable formulas, outputs and tests for its declared scope. Merely documenting a formula is completion of specification work, not model implementation. This resolves the source's conflicting “implemented or documented” and “no prose-only formulas” wording without adding an unrelated product condition.

## 7. Deferred work

Full DAG simulation, additional tables where unnecessary, ML/Bayesian upgrades and statistical coverage calibration remain later work unless explicitly selected. Calibrate only when adequate observed outcomes exist, as the source states. Do not require long-term production-customer observation collection before functional acceptance of the rule-based iteration, and do not present unmeasured P80/P90 coverage as established accuracy.

Preserve existing useful GLTG client/model work, tests and version history. Freeze unselected expansion rather than deleting it. Aivan's product can be assessed for its delivered flow without pretending that all future dependency research has already finished.
