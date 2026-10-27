# CTYun Deployment Notice

Reconciled: 2026-10-02. **NO DEPLOYMENT AUTHORIZED.** This file provides no executable host-changing procedure.

The earlier runbook was quarantined because it contained stale host/model assumptions and unsafe service-changing instructions. Use the current authorized target inventory when an operation is requested. The [deployment safety notice](DEPLOY_OPENCLAW_AIVAN_SOP.md) preserves the existing port, service, bridge, credential and authorization boundaries.

HTTPS defaults to port 443 and SSH to port 22. If a default is occupied, select an alternative verified as unoccupied; no port number, including 443 or 8443, is permanently forbidden. Verify current listeners and coordinate shared proxy routes and certificates with the deployment owner without displacing unrelated services or mail/MX. Record the selected ports and actual access URL, update applicable proxy/firewall configuration and delivery instructions, and verify the connection and HTTPS readback. This supersedes the earlier static port restrictions, not the requirement for applicable deployment authorization or actual platform permission. CTYun external routing must use the authorized `abcdyi-sin` Singapore bridge. This documentation does not install/replace a model, change credentials or network policy, run migrations, mutate a production DB or restart services.

The historical environment note identified `qwen3.5:9b`. Verify the actually installed model for any authorized operation; that historical name does not mandate a model, authorize a download/replacement or redefine the product.

The selected database/provider can vary under the product's hot-swappable private-data contract. A particular CTYun/MySQL/SQLite profile is an environment-specific compatibility claim, not a universal product definition. The two designated simulated DBs are valid functional acceptance sources through actual application/API execution.

The existing no-deployment workflow and preflight evidence do not prove deployment. Report the exact target revision and actual user-flow evidence only after the corresponding authorized operation has run. Do not require an unrelated full operations program before accepting a demonstrated bounded product function.
