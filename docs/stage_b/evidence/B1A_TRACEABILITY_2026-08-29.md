# AIVAN Stage B1-A traceability

Status: local implementation candidate. Independent audit, required GitHub CI,
CodeQL, and merge authorization remain outstanding.

Baseline: `main@ae9f91001c8291ca4fe25c3f1323706adb3c4dec`, tree
`a5a50ef683b7dddb105b707a5c22c5a40ee752bf`.

| Requirement | Implementation | Exact regression evidence | Local state |
|---|---|---|---|
| B1A-01 provider-neutral, versioned result | Immutable `DependencyProbeSpec` / `DependencyProbeResult`; stable contract, status, owner, criticality, SLO, expected/observed version, correlation | `tests/stage_b/test_dependency_probe_contract.py::test_all_required_dependencies_declare_probe_version_slo_and_owner` | Passed |
| B1A-02 real HTTP orchestration and version fail-closed | `run_dependency_probes` uses real `httpx.Client` by default, refuses injected transports in production, disables redirects, validates URL shape, health and version envelopes | `tests/stage_b/test_dependency_probe_contract.py::test_required_dependency_version_mismatch_is_not_ready` | Passed |
| B1A-03 `/readyz` is not config-only green | Production readiness executes all four critical probes and requires fresh ready results | `tests/stage_b/test_dependency_probe_contract.py::test_readyz_calls_real_probes_and_rejects_config_only_green` | Passed |
| B1A-04 stable redaction and correlation | Public result excludes URL, headers, response body, exception text and credentials; only stable codes and safe correlation are emitted | `tests/stage_b/test_dependency_probe_contract.py::test_probe_timeout_returns_stable_code_and_correlation_without_provider_details` | Passed |
| B1A-05 exception-safe counters | HTTP failures are counted in `finally`; dependency counters use only fixed dependency/criticality/status labels | `tests/stage_b/test_metrics_persistence.py::test_failed_requests_are_counted_when_call_next_raises` | Passed |
| B1A-06 zero business side effects on critical failure | Authenticated production mutations for quote/invoke, approval, outbound, progression and relay are gated before handlers; unauthenticated callers cannot trigger probes | `tests/stage_b/test_side_effect_zero.py::test_critical_dependency_failure_records_zero_outbound_approval_and_progression_effects` | Passed |

## Declared critical dependencies

| Dependency | Owner | Endpoint class | Production expectation |
|---|---|---|---|
| giraffe-db | DB | tenant data contract | authenticated schema/contract response and exact reviewed version |
| GLTG | GLTG | lead-time service | explicit health plus exact reviewed API version |
| OpenClaw | OpenClaw | managed outbound gateway | authenticated health response with exact reviewed version |
| giraffe-language-skill | giraffe-language-skill | authoritative translation service | explicit health plus exact reviewed service contract version |

Expected versions and timeout/staleness SLOs are deployment-owned environment
configuration. Missing values, invalid endpoints, failed health, timeouts,
unversioned responses, version mismatch, or stale observations remain not ready.

## Scope proof

- No DB schema, migration, giraffe-db, GLTG, GPM, MyAivan, server, deployment,
  alert persistence, acknowledgment, escalation, close, or restart semantics were
  added or modified.
- Probe observations and counters are process-local telemetry, not canonical
  alert or business-fact storage.
- B1-B, Stage C-F, production deployment, and merge remain unauthorized.
- GLTG evidence dependency is refreshed to remote head
  `03b02dcfbfd5ab89ead68f8e11e96f7a3b5271bd`; GLTG S1 remains FAILED because
  Real HTTP E2E is skipped-success, so this candidate makes no GLTG acceptance
  claim.

## Local gates

- Authorized RED baseline: 6 failed, saved as digestible JUnit evidence.
- Authorized focused tests: 6 passed.
- Focused compatibility regression: 11 passed.
- Full pytest: 894 passed, 2 skipped.
- Ruff full repository: passed.
- Mypy 1.17.0 safety boundary: 28 files, no issues.
- Bandit 1.8.6 high severity: no findings.
- Compileall: passed.
- Module size budget: passed (`main.py` 1400/1400,
  `rfq_execution.py` 995/1000).
- `git diff --check`: passed.

The final commit/tree, PR, CI/CodeQL, file digests, and no-drift snapshot are
recorded in the external audit manifest after the candidate is frozen.
