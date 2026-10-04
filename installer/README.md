# MyAivan integrated Linux installer

This package installs a prebuilt CPython 3.12 runtime, MyAivan web application,
standalone GPM, GLTG, giraffe-db, and giraffe-language-skill. The installation
machine does not need Python, pip, uv, Docker, Git, a compiler, or a source checkout.
Only ordinary Linux tools (`sh`, `tar`, `tail`, `awk`, `sha256sum`, `mktemp`) are used
before the included Python runtime takes over. All provider code remains in its
own namespace and is supplied as independent pinned build inputs.

## Install

Verify the separately delivered SHA-256 checksum before executing the package.
Run the single installer, for example:

```sh
sh myaivan-RELEASE-linux-x86_64.run --prefix "$HOME/MyAivan Server" \
  --tenant enterprise-a --tenant enterprise-b
```

The installer creates and starts all five services, initializes empty databases,
and creates local installation credentials with private permissions. Existing
ports are never taken over. All default listeners use loopback and automatically
allocated, recorded, unprivileged ports. No production host, DNS, firewall, SSH,
existing bridge, email account or business record is changed by building/testing
this package. CTYun profiles reject its protected ports 443 and 8443.

Use a dedicated directory owned by the installing user with mode 0700. Re-running
the same package preserves data, configuration, credentials and selected ports.
The generated `config.json` contains secrets. Do not publish it or attach it to
support reports. Frontend tenant credentials differ; the trusted loopback provider
network uses its separate internal service credentials plus verified tenant IDs.
The bundled provider API does not claim independent per-tenant service secrets.
Do not expose the provider ports publicly.

## Manage

```sh
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
  --host-profile sin --model-url http://127.0.0.1:11434 \
  --model-name EXISTING_MODEL --restart
```

Additional flags include `--web-port` for a confirmed allocation,
`--language-model-dir` for an existing model directory, `--language-url` for an
existing compatible language service, and `--database-url` for a compatible private
DB API. These configure the whole installation; no source editing or separate
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
external API replaces its bundled service. The `external.aivan_database_url`
setting preserves the application SQLAlchemy database-provider boundary; the
installer never bootstraps or migrates an external database. Its selected schema
must already be compatible. External service credentials must be provided through
the private configuration by an authorized operator.

The default public origin is `https://myaivan.com`. Production browser sessions
use secure cookies and require an authorized HTTPS ingress to the recorded web
listener. No public route, TLS certificate or port allocation is invented. The
existing CTYun/SIN bridge is not replaced. Public deployment and target-host
compatibility remain separate from a local package lifecycle test.

## Language, model and channel state

The package includes the offline statistical canonical-English validator and
native CTranslate2 translation dependencies. Translation model weights are not
included; configure a verified existing model directory or compatible language
service. Non-English workflow must fail closed without a functioning dynamic
language provider. Do not select a mock provider to mark readiness green.

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
configuration, and switches the release pointer atomically. A failed start restores
the previous release and pre-upgrade local data snapshot. Failed-upgrade data is
retained alongside the backup for inspection. Existing schemas are only validated;
unapproved schema migrations fail without modifying the schema.

`myaivan rollback` switches to the retained previous compatible release and keeps
current data. It does not silently discard business writes made after an upgrade.
An incompatible older schema is rejected and the current release is recovered.
External DB restore/migration is intentionally not attempted by this controller.

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
registers and starts one user unit for the entire five-service supervisor.
`myaivan service-uninstall` disables and removes only that installation's unit.
Normal installation does not require systemd and continues to support containers.

This option does not enable lingering, modify system-wide units or change user
accounts. Startup occurs when the existing user manager starts; unattended reboot
behavior depends on that host's already authorized user-manager configuration.
An unavailable user manager fails before stopping the working manual installation.
Unit generation and command handling are tested with isolated fixtures. An actual
host reboot/user-manager startup test has not been performed in this environment.
