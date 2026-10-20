# Aivan / OpenClaw Deployment Safety Notice

The existing workflow records candidate metadata and performs no deployment.

## Existing workflow meaning

`.github/workflows/deploy-server.yml` is a no-deployment record. Its success does not show that a host was contacted, a secret read, a service updated, a migration applied, a channel exercised or a user flow accepted. Keep that evidence truthful.

## Target-specific protections retained

Deployment-specific reserved ports, service ownership and egress routes come from the selected target configuration. Verify that configuration before deployment; preserve existing services and the configured network route.

Secrets belong in the configuration/secret store, not source, Action inputs, logs or evidence.

## Deployment verification

Identify the exact candidate, target, applicable DB profile, planned changes and rollback/recovery needs. Verify the applicable operational safeguards, preserve data and existing services, and report the actual deployed revision and results. Existing predeployment/migration tools may help, but their old fixed-provider/stage assumptions must not silently override current product requirements.

There is no mandatory Stage 7F product phase, all-channel test bundle, institutional signature chain or full capacity/observability program imposed by this notice. Functional acceptance using the designated simulated DBs follows [Acceptance Criteria](ACCEPTANCE_CRITERIA.md); it is not dependent on first performing a production-host deployment.

## Authorization boundary

The record-only workflow and this document do not authorize deployment. Obtain the applicable operator authorization for the exact target and planned deployment, migration, database mutation, service restart, account or network change. External business or test messages require their own authorized recipient and purpose. Preserve privacy, least privilege and secret-store boundaries; do not bypass a denied action or disclose private operational data.
