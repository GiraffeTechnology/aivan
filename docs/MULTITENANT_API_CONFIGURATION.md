# Multi-tenant API configuration

For one hosted MyAivan service serving multiple tenants, configure
`AIVAN_ENV=production` and an `AIVAN_TENANT_API_KEYS` JSON object mapping tenant
IDs to distinct access credentials. Leave `AIVAN_TENANT_ID` unset; setting it
deliberately restricts the deployment to that single tenant. The sign-in form
accepts the tenant ID and exchanges the matching credential for an HttpOnly,
Secure, SameSite session. Credentials are never saved in browser storage.

Session role changes remain limited to the operator identity and role allowlist
configured by the service administrator. Tenant selection does not permit role
selection beyond that allowlist. Removing a tenant from the configured key map
revokes that tenant's existing production UI sessions. Sessions for a retained
tenant keep their existing expiration when only that tenant's API key rotates.

## GPM service credentials

The standalone GPM ASGI app is `aivan.gpm.server:app`. Give its inbound
`AIVAN_TENANT_API_KEYS` distinct tenant credentials. On the Aivan consumer, set
`GPM_TENANT_API_KEYS` to the matching tenant-to-GPM-credential JSON object.
The consumer selects the downstream credential using the authenticated tenant,
never a body-supplied tenant. A configured map is authoritative: malformed maps
and missing tenant entries fail closed, even if `GPM_API_KEY` is also present.
`GPM_API_KEY` remains the compatibility profile when no tenant map is configured.

With `AIVAN_LLM_API_ENABLED=false`, GPM generates deterministic comparisons of
the supplied quote totals without calling a model. It reports missing benchmark
evidence, low confidence and required human review; it does not invent market
advice. The packet explicitly reports `runtime_status=disabled` and
`model_provider=none`. With model calls enabled, a configured provider failure
remains a failure, and external model policy is enforced before provider access.
A reachable health endpoint or a replayed packet does not prove model availability.

## Private provider boundary

The reference private DB and GLTG use privileged internal service credentials
with authenticated tenant headers. Bind these services to the private
loopback/service network and expose them only through the authenticated product
backend. Do not expose their service credentials to the browser. Those internal
credentials are not independently tenant-scoped credentials.

Configure the same `GIRAFFE_DB_SERVICE_AUTH_SECRET` on the reference DB and its
authorized internal consumers, and set `GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET` to
that value for GLTG. Configure `GLTG_INBOUND_SERVICE_AUTH_SECRET` on GLTG and
`GLTG_SERVICE_AUTH_SECRET` on its Aivan consumer. Keep every service endpoint
explicitly configurable. Production DB writes also require the real canonical
language validation API. No port allocation or production deployment is
authorized by this document.
