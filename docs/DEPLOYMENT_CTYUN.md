# CTYun Deployment Notice

Reconciled: 2026-10-02. **NO DEPLOYMENT AUTHORIZED.** This file provides no executable host-changing procedure.

The earlier runbook was quarantined because it contained stale host/model assumptions and unsafe service-changing instructions. Use the current authorized target inventory when an operation is requested. The [deployment safety notice](DEPLOY_OPENCLAW_AIVAN_SOP.md) preserves the existing port, service, bridge, credential and authorization boundaries.

Aivan host ports 443/8443 and their existing services must not be taken over. CTYun external routing must use the authorized `abcdyi-sin` Singapore bridge. This documentation does not install/replace a model, change credentials or network policy, run migrations, mutate a production DB or restart services.

The historical environment note identified `qwen3.5:9b`. Verify the actually installed model for any authorized operation; that historical name does not mandate a model, authorize a download/replacement or redefine the product.

The selected database/provider can vary under the product's hot-swappable private-data contract. A particular CTYun/MySQL/SQLite profile is an environment-specific compatibility claim, not a universal product definition. The two designated simulated DBs are valid functional acceptance sources through actual application/API execution.

The existing no-deployment workflow and preflight evidence do not prove deployment. Report the exact target revision and actual user-flow evidence only after the corresponding authorized operation has run. Do not require an unrelated full operations program before accepting a demonstrated bounded product function.
