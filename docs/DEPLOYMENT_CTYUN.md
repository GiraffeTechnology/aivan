# Deployment Configuration Notice

This file is a configuration reference and contains no executable host-changing procedure.

Deployment-specific protected ports, existing services and egress routes come from the selected target configuration. Preserve configured reservations and service ownership. The [deployment safety notice](DEPLOY_OPENCLAW_AIVAN_SOP.md) describes these boundaries.

The selected model and database/provider must be verified against deployment configuration. A model label or database engine in an example does not establish the installed configuration or mandate a replacement. The two designated simulated DBs remain valid functional acceptance sources through actual application/API execution.

The existing record-only workflow and preflight evidence do not prove deployment. Report the exact deployed revision and actual user-flow evidence after execution.

The predeployment descriptor must match `AIVAN_DEPLOYMENT_PROFILE`, `AIVAN_DEPLOYMENT_CLOUD`, `AIVAN_EXPECTED_EGRESS_POLICY` and `AIVAN_REVERSE_BRIDGE_PORT`. The runtime egress policy must match the nonempty expected policy. Missing or mismatched configuration fails closed. Reverse-bridge binding remains loopback-only and uses the required `/health` path; protected-port and independently recorded live-observation checks remain required.
