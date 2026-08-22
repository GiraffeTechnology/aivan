# CTYun deployment notice — quarantined

Status: **NO DEPLOYMENT AUTHORIZED. THIS FILE CONTAINS NO EXECUTABLE DEPLOYMENT PROCEDURE.**

The former post-PR29 runbook was removed because it pinned an obsolete commit and
model, instructed CTYun to contact GitHub directly, and included commands that
could replace files, models, dependencies, or running services. Those actions
conflict with the current infrastructure and authorization constraints.

The authoritative safety boundary is
[`DEPLOY_OPENCLAW_AIVAN_SOP.md`](DEPLOY_OPENCLAW_AIVAN_SOP.md). In particular:

1. CTYun traffic to IP addresses outside mainland China must use the authorized
   `abcdyi-sin` Singapore bridge. Direct GitHub access from CTYun is prohibited.
2. AIVAN host ports `443` and `8443` are occupied by SSH/MAIL. AIVAN and myAIVAN
   must not bind, proxy, remap, restart, or otherwise change them.
3. The currently reported local model is `qwen3.5:9b`. Repository documentation
   is not permission to download, remove, replace, or reconfigure a model.
4. Passwords, private keys, access keys, secret keys, and tokens are injected
   only by the authorized secret store and must never enter this repository,
   Actions inputs, logs, or evidence.
5. Without a specific Stage 7F authorization, do not deploy, migrate, write a
   production database, send a message, modify DNS/CDN or reverse proxy state,
   restart a service, or change a port.

## Permitted activity before Stage 7F

Only offline repository validation and digest-only `automated_preflight`
evidence are permitted. A successful preflight is not production acceptance and
must retain `production_acceptance=false`.

Any future executable runbook must be introduced by a separate PR after GitHub
Environment approval, candidate SHA freeze, migration/backup/restore review,
port and bridge evidence, rollback review, and explicit project-owner sign-off.
