# MyAivan integrated Linux installer

This package installs a prebuilt CPython 3.12 runtime, MyAivan web application,
standalone GPM, GLTG, giraffe-db, giraffe-language-skill, and the independently
pinned abcdYi fulfillment API. The installation
machine does not need Python, pip, uv, Docker, Git, a compiler, or a source checkout.
Only ordinary Linux tools (`sh`, `tar`, `tail`, `awk`, `sha256sum`, `mktemp`) are used
before the included Python runtime takes over. All provider code remains in its
own namespace and is supplied as independent pinned build inputs.

## Install and explicitly prepare SQL databases

The production profile uses the operator's authorized MySQL databases. PostgreSQL
compatibility is retained. No database URL, account, server or namespace is guessed.
The package includes synchronous and asynchronous SQL drivers. No Python, pip,
compiler or Git installation is needed on the target machine.

Keep SQL connection settings in an existing private operator-owned file outside
the release/package. The installer stores only its absolute file reference.
The file must be readable only by its owner. This example contains placeholders:

```json
{
  "version": 1,
  "databases": {
    "aivan": {"url": "mysql+pymysql://APP_USER:URL_ENCODED_PASSWORD@MYSQL_HOST/AIVAN_DATABASE"},
    "abcdyi": {"url": "mysql+aiomysql://APP_USER:URL_ENCODED_PASSWORD@MYSQL_HOST/ABCDYI_DATABASE"},
    "database": {"url": "mysql+pymysql://APP_USER:URL_ENCODED_PASSWORD@MYSQL_HOST/PROVIDER_DATABASE"}
  }
}
```

Use distinct database namespaces: the three applications contain overlapping table
names. For PostgreSQL, distinct preconfigured schemas are also supported with a
`schema` field; the connected account's actual default schema must match. The
installer does not create DB servers, database accounts or physical databases.
Fresh MySQL tables use binary UTF-8 identity comparisons. The plan reports existing
incompatible identity collations; it does not automatically convert their data.
Actual target addresses and SSH metadata belong only in the private manual
handoff, never in repository examples, PR text or public verification artifacts.

Verify the separately delivered package checksum, then stage it without startup:

```sh
sh myaivan-RELEASE-linux-x86_64.run --prefix "$HOME/MyAivan Server" \
  --tenant TENANT_ID --database-config-file /private/database-config.json --no-start
"$HOME/MyAivan Server/myaivan" database-plan --plan-file /private/database-plan.json
```

`database-plan` inspects the selected SQL targets without changing their schemas.
It records the package identity, target/namespace hashes, current migration heads,
and missing schema elements. Even when one component is selected, planning first
checks physical namespace isolation across all configured SQL targets, so hostname
aliases cannot hide overlapping application databases. Only selected components
are migrated. Preview and verify the applicable recoverable backup
before the explicitly authorized migration:

```sh
"$HOME/MyAivan Server/myaivan" database-migrate \
  --plan-file /private/database-plan.json --tenant-id TENANT_ID \
  --authorization-reference AUTHORIZED_CHANGE_REFERENCE \
  --backup-reference VERIFIED_RECOVERY_REFERENCE --bootstrap-empty
"$HOME/MyAivan Server/myaivan" start
```

Use `--bootstrap-empty` only for verified empty application databases. Fresh native
abcdYi initialization creates the pinned current metadata and explicitly records
the Alembic head as its baseline. Existing versioned targets execute the pinned
migration chain and declared additive table creation; populated unversioned targets
are not silently stamped. The Aivan migration stages are bundled and verified
against the package inventory. No Git checkout is required on the target.

A changed package, target or schema invalidates an earlier plan. Migration receipts
record completed and failed components separately: there is no claim of one atomic
transaction across three databases. A partial failure remains a failure and needs
a fresh plan before resuming. Startup validates external schemas and never silently
migrates them, creates a replacement SQLite DB or resets business records.

A configured external private-provider HTTP API replaces the bundled provider
service. In that profile, omit `databases.database`; keep the Aivan and abcdYi SQL
targets. `setup --database-url` refers to this HTTP API, not a SQL URL. Use
`--database-provider-id` to retain the correct logical store identity.

For an explicitly isolated local test only, `--isolated-sqlite` selects local
SQLite databases. It cannot be used with a production host profile. Production
installation defaults to external SQL and fails closed on blank/unreadable config.

Use a dedicated prefix owned by the installing user. Generated installation service
credentials remain in the private `config.json`; SQL credentials remain in the
operator's external file. Do not publish either file or raw logs containing private
configuration. Startup uses loopback listeners and preserves existing port owners.
No production DNS, firewall, SSH, bridge or existing maintenance service is changed
by this package's build/tests. Deployment follows the authorized private handoff.

## Manage

```sh
"$HOME/MyAivan Server/myaivan" check
"$HOME/MyAivan Server/myaivan" health
"$HOME/MyAivan Server/myaivan" stop
"$HOME/MyAivan Server/myaivan" start
"$HOME/MyAivan Server/myaivan" restart
"$HOME/MyAivan Server/myaivan" recover
"$HOME/MyAivan Server/myaivan" verify
```

The supervisor owns only its recorded processes, identifies them using PID plus
Linux process start time, and restarts failed child services with bounded backoff.
Repeated failures remain failures. `recover` clears a stopped/crashed instance and
restarts it without resetting data. A health pass is service liveness; it is not a
claim that public-domain routing, translation or a model-dependent quote succeeded.

## Configure endpoints and tenant mappings

Use the guided CLI flags to preserve generated credentials while selecting existing
services. For example, with an already authorized local model:

```sh
"$HOME/MyAivan Server/myaivan" setup --origin https://myaivan.com \
  --host-profile other --model-url http://127.0.0.1:11434 \
  --model-name EXISTING_MODEL --restart
```

Additional flags include `--web-port` for a confirmed allocation,
`--language-model-dir` for an existing model directory, `--language-url` for an
existing compatible language service, and `--database-url` with `--database-provider-id` for a compatible private
DB HTTP API. `--database-config-file` selects authorized SQL settings through a private file reference. These configure the whole installation; no source editing or separate
component deployment is required. `--restart` restores the previous configuration
and services if the changed profile fails its startup checks.

For advanced private settings, stop services, edit a private copy of `config.json`, then use:

```sh
"$HOME/MyAivan Server/myaivan" configure --file /private/reviewed-config.json
"$HOME/MyAivan Server/myaivan" start
```

The configuration accepts the public origin, confirmed ports, tenant-key map,
existing private model endpoint/model name, translation model directory or language
service endpoint, and external compatible database/GLTG/GPM API endpoints. An
external API replaces its bundled service. The SQL targets are selected by the private file described above. External schemas
change only through the explicit plan/migrate workflow; startup only validates them. External service credentials must be entered by the authorized operator into an
owner-only credential file. Use `service-configure --file /private/services.json`
locally after selecting endpoints, then `prepare --service-credentials-file
/private/services.json`. The runtime validates exact tenant coverage; a missing
tenant credential never falls back to a different tenant. Endpoint-only configuration
may be staged with `prepare` or `--no-start`, but starting or restarting requires
explicit credentials for every selected external database, GLTG and GPM service.
Installation-owned frontend and bundled-service keys are never borrowed for those
external destinations. Health reports `credentials_required` without probing an
unconfigured external service; authenticated non-loopback probes require HTTPS.

The default public origin is `https://myaivan.com`. Production browser sessions
use secure cookies and require an authorized HTTPS ingress to the recorded web
listener. No public route, TLS certificate or port allocation is invented. The
existing operator-managed ingress is not replaced. Public deployment and target-host
compatibility remain separate from a local package lifecycle test.

## Language, model and channel state

The package includes the offline statistical canonical-English validator and
native CTranslate2 translation dependencies. Translation model weights are not embedded in the `.run` file. The complete
delivery may include a separately checksummed optional Chinese/English model cache.
Select that verified cache with `prepare --language-model-dir`, or configure an
existing compatible language service. No conversion or dependency installation is
required on the target. Non-English workflow must fail closed without a functioning dynamic
language provider. Do not select a mock provider to mark readiness green.

The installed translation runtime uses CTranslate2 and SentencePiece directly.
Model-conversion/training tools such as Transformers are not runtime dependencies
and are not shipped in this installer.

GPM is a real API service and uses the existing zero-model mode by default.
That mode performs recorded-price arithmetic and returns low-confidence,
insufficient-market-data guidance requiring human review; it does not claim model
analysis. Configure an authorized existing private Ollama endpoint/model to enable
model-assisted guidance. An enabled model's actual failure remains a failure.
No model weights are bundled and no cloud credentials are generated or read from
the build host. English API/data workflows and canonical validation can run without
translation weights or a model. Selected business-flow acceptance is established
by real workflow tests, never inferred from a process health response.

Email is unconfigured with the existing manual-copy fallback. IM remains manual
copy/send/confirmation. The installer does not send business messages, enable
external model calls, or waive human commercial approval.

## Upgrade, rollback and removal

Run a newer installer against the same prefix. The controller verifies the complete
file inventory before activation, stops its own services, backs up local data and
configuration, and switches the release pointer atomically. A failed start can restore
the previous compatible release and pre-upgrade local data snapshot. A failed switch
to external SQL does not automatically restart an older local database profile. Failed-upgrade data is
retained alongside the backup for inspection. Existing schemas are only validated;
unapproved schema migrations fail without modifying the schema.

`myaivan rollback` switches to the retained previous compatible release and keeps
current data. It does not silently discard business writes made after an upgrade.
An incompatible older schema is rejected and the current release is recovered.
External database restoration is never implied by package rollback. A previous
release that cannot preserve the external SQL profile is rejected before rollback.
SQL migration is the separate explicit operation described above.

`myaivan uninstall` stops owned processes and removes the active launcher/pointer.
Data, private configuration, backups and release binaries remain for recovery.
Re-running the original installer reactivates the installation. Deleting retained
data is a separate explicit operator action.

## Build and provenance

`build.py --help` describes required source paths, exact upstream revisions and
verified Git trees. Build on Linux x86_64 using a relocatable CPython 3.12 runtime.
The build machine uses `uv` and can use a SHA-verified provider source manifest
that reconstructs the exact upstream Git tree, with every included runtime blob
verified separately. Private synthetic datasets are not bundled. The build machine uses `uv`; the install machine does not. Third-party dependencies
are pinned with hashes in `requirements.lock`, constrained to Aivan's tested lock.
Each package contains a complete SHA-256 file manifest, component upstream trees,
local patch/content hashes, wheel hashes, installed dependency SBOM and licenses.
The builder verifies installed runtime imports from outside the source checkout.

The ABI report scans every shipped ELF object for glibc symbol requirements and
records the actual build/test host. This does not certify execution on an older
server that was not tested. Target architecture is Linux x86_64, not Windows/macOS.
Provider sources and private test fixtures must never be published into Aivan or
other repositories. This installer source contains no provider source or fixtures.

## Optional user-service startup

On a host with a functioning current-user systemd manager, `myaivan service-install`
registers and starts one user unit for the entire six-service supervisor.
`myaivan service-uninstall` disables and removes only that installation's unit.
Normal installation does not require systemd and continues to support containers.

This option does not enable lingering, modify system-wide units or change user
accounts. Startup occurs when the existing user manager starts; unattended reboot
behavior depends on that host's already authorized user-manager configuration.
An unavailable user manager fails before stopping the working manual installation.
Unit generation and command handling are tested with isolated fixtures. An actual
host reboot/user-manager startup test has not been performed in this environment.


## Confirmed-order handoff to abcdYi

Installation reports a separate loopback `fulfillment_url`. The existing tenant
ID/API credential can obtain a short-lived token from
`POST /api/installation/session`, with headers `X-AIVAN-Tenant-ID` and
`X-AIVAN-API-Key`. No separate account or password provisioning is required.
Use the returned bearer token for the normal fulfillment API, including
`POST /api/orders/from-provider-confirmed` with `{"purchase_order_id":"<confirmed PO ID>"}`.
The PO must already be human-confirmed through Aivan in the same selected private
data provider. Import does not confirm a quote or send an external commitment.

Each configured tenant has its own persisted execution tenant/operator identity
and provider mapping. The bridge rejects a key paired with another tenant and
retains normal project, role and lifecycle authorization. Its additional login
route is provided only by this installation-owned launcher, not by changing
upstream abcdYi authentication defaults.

The execution view uses the configured external MySQL/PostgreSQL database. Its
initialization/migration follows the explicit verified plan; local `data/abcdyi.db`
is used only when the operator explicitly selects the isolated test profile. Existing schemas are validated and never
silently rewritten; an incompatible upgrade fails and restores the previous
release/configuration. Supported explicit schema migrations must be supplied by
a compatible release. Provider-owned business history remains authoritative.
Restart, reinstallation and rollback retain the execution database and identities.

The abcdYi `api`/`src` source is inventoried under `services/abcdyi`, loaded only
inside its process. It is not installed as a wheel that could replace the current
top-level Aivan/GPM implementation. The builder requires independent abcdYi source,
revision and Git-tree inputs and checks offline imports from outside all checkouts.


### Private provider identity

The installation records a logical identity for its private-data store. When
selecting another store, supply `setup --database-url URL --database-provider-id ID`.
Use a different identity for an independent store even if it reuses purchase-order
IDs. Retain the identity only when an endpoint move preserves the same business
records and ownership. Returning to the bundled store restores its original
installation-owned identity. Credentials and provider IDs remain separate.


## Prepare without writing configuration by hand

Install with `--no-start` first. On the target's private interactive terminal, run
`myaivan database-configure --file /absolute/private/database-config.json` to enter
the three existing MySQL connections. Password input is hidden and never accepted
from command arguments. Select the resulting file with `prepare
--database-config-file /absolute/private/database-config.json`. The tool does not
create database users, accounts, grants or physical databases. An existing approved
private connection file can be used directly instead.

`prepare --profile-file /absolute/private/deployment.json` merges nonsecret values
without replacing installation-owned API credentials or tenant identities. The
version-1 profile supports `origin`, `host_profile`, `requested_ports`,
`reserved_ports`, `runtime_threads`, `database_config_file`,
`service_credentials_file`, `private_data_provider_id`, `external`, `language`,
`model` and `channels`. It rejects unknown fields and tenant replacement. Profile
and credential files must be regular, owner-only files, not symbolic links.

Ports are requested allocations, not assumptions. The supervisor chooses a free
loopback port when a requested port is occupied or reserved, preserves the existing
listener, rewires its managed dependencies and atomically publishes actual values
to `run/ports.json`. Environment reservations can also use `AIVAN_RESERVED_PORTS`.
Host profile names do not reserve any port. The reservation list is empty unless
the deployment supplies it. Internal listeners remain non-root, unprivileged
ports (1024 through 65535), with zero requesting automatic allocation; the public
HTTPS origin may use its standard default port independently of those listeners.
The selected reservations are passed to application readiness through
`AIVAN_RESERVED_PORTS`. Readiness validates the configured value; actual occupied
ports are protected by the supervisor's real listener allocation.
Ingress must use the published `web` value after startup. `check` verifies every
release file and authenticated per-tenant durable GPM readiness, as well as the
other services. It does not substitute for public TLS or business acceptance.

An existing OpenClaw email gateway is optional. Select it with `prepare
--openclaw-url URL`, enter its existing API key with `service-configure`, and enable
email explicitly using `prepare --enable-email`. `--disable-email` restores the
manual-copy path. Enabling a gateway never grants commercial approval; the normal
preview and human-confirmation gates remain mandatory. IM remains manual.

The optional local translation cache supports Chinese to English and English to
Chinese only. It is replaceable through the existing language-provider interface.
Other language pairs require separately verified provider/model support; language
detection alone does not imply translation coverage. Runtime threads default to
two to avoid exhausting a shared host.

Commercial translation is fail-closed. A changed or unverifiable quantity,
currency, unit, percentage or date leaves the draft pending; no incorrect value
is repaired silently. If a selected translation cannot be verified, the operator
can retry or explicitly select English and generate a new preview of the original
canonical draft. That English preview needs its own human review and approval;
it is never presented as a successful translation into the failed target language.


## Provision a separate buyer without SQL or source editing

After the schema plan/migration and normal startup, an approved local operator can
run `myaivan buyer-create --tenant TENANT_ID --email BUYER_LOGIN_EMAIL --full-name
"BUYER PROFILE NAME"` in a private interactive terminal. The buyer's chosen
password is entered twice with hidden input, never in command arguments or an
exported configuration file. The command creates only a same-tenant BUYER role,
stores a password hash, records an audit event and returns the new user ID.
It never changes an existing email account, resets passwords, grants platform
admin or assigns a project automatically. Noninteractive invocation is rejected.

The buyer uses normal `POST /api/auth/login` on the fulfillment API. An authorized
project administrator must explicitly assign the returned buyer user ID through
the existing project membership API before buyer-only decisions. This preserves
a separate buyer identity and normal tenant/project/role checks. Account creation
is not buyer approval, order confirmation or sign-off. Real account/password
creation remains an action of the approved operator, not a build-time fixture.
