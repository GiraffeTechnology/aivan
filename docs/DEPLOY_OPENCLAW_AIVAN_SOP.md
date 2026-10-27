# Aivan / OpenClaw Deployment Safety Notice

Reconciled: 2026-10-02. The existing deployment workflow is quarantined: it records a candidate/authorization reference and performs no deployment. A documentation change or successful workflow does not authorize production mutation.

## Existing workflow meaning

`.github/workflows/deploy-server.yml` is a no-deployment record. Its success does not show that a host was contacted, a secret read, a service updated, a migration applied, a channel exercised or a user flow accepted. Keep that evidence truthful.

## Target-specific protections retained

For authorized CTYun Aivan operations, HTTPS defaults to port 443 and SSH to port 22. If a default is occupied, use an alternative verified as unoccupied; do not treat 443, 8443 or any other port number as permanently forbidden. Verify actual listeners, proxy routes and certificate ownership, and coordinate shared bindings with the existing deployment owner. Do not stop or overwrite unrelated applications or mail/MX to free a port. Record the selected ports and actual access URL, update applicable proxy/firewall configuration and delivery instructions, and verify the connection and HTTPS readback. This supersedes earlier static port restrictions without bypassing actual permission denials. CTYun connections outside mainland China use the authorized `abcdyi-sin` route; do not invent a bypass. Resolve actual target identity/configuration through the authorized operations inventory rather than stale addresses in historical documents.

Secrets stay in the authorized configuration/secret store, not source, Action inputs, logs or evidence. Production deployment, migration, database mutation, service/network changes and external business/test messages each require the applicable authorization. A known channel or approved draft does not authorize arbitrary new sending.

## Scope of a future operation

When a deployment is requested, identify its exact candidate, target, applicable DB profile, planned changes and rollback/recovery needs. Verify only the operational safeguards needed for that authorized change, preserve data and existing services, and report actual deployed revision and results. Existing predeployment/migration tools may help, but their old fixed-provider/stage assumptions must not silently override current product requirements.

There is no mandatory Stage 7F product phase, all-channel test bundle, institutional signature chain or full capacity/observability program imposed by this notice. Functional acceptance using the designated simulated DBs follows [Acceptance Criteria](ACCEPTANCE_CRITERIA.md); it is not dependent on first performing a production-host deployment.
