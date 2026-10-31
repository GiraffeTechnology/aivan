# Rebuild the integrated r20 candidate offline

This candidate contains the full frozen r18 Python runtime and six application
services, with the reviewed r19 Core channel alias integrated into the installed
Aivan package. It is an offline derived-payload build, not a newly compiled
Python distribution, a wheel rebuild, or a new upstream Git commit.

The existing `build.py` remains the independent pinned-source/wheel builder.
`build_derived.py` is the bounded reconstruction path for these supplied inputs.
It verifies the frozen installer and every payload file, validates the full
candidate source against the original snapshot plus the exact reviewed patch,
checks unchanged provider source and dependency lock, updates installed Aivan
distribution metadata and file hashes, runs offline imports, scans all ELF
dependencies, and emits a new complete self-extracting installer.

## Inputs and command

Use a Linux x86_64 builder with Python 3.12 or later, Git, `readelf`, `ldd` and
ordinary base-system tools. No network access or package installation is used.
The frozen installer, source snapshot and reviewed patch are required and pinned
by SHA-256 in the builder. The source root contains the five full component
directories (`aivan`, `abcdyi`, `database`, `gltg`, `language`).

```sh
python3 SOURCE_ROOT/aivan/installer/build_derived.py \
  --base-installer FROZEN_R18/myaivan-2026.10.08-candidate-r18-linux-x86_64.run \
  --source-root SOURCE_ROOT \
  --source-snapshot SOURCE_ROOT/source-snapshot-manifest.json \
  --reviewed-patch r19-local-compatibility.patch \
  --output OUTPUT
```

The source snapshot is explicitly the frozen r18 baseline. New files
`*-source-inventory.json` and `*-source-delta.json` describe the actual r20 source.
`*-derived-build.json` identifies the base, reviewed patch, builder, changed
files and limitations. Upstream revision fields retain the true base commits;
Aivan is explicitly marked modified. Original wheel hashes are under
`frozen_base_wheels`; the new `wheels` mapping is empty because this build does
not claim freshly built wheels. Binary artifact hashes may change across rebuilds
because archive timestamps are not normalized.

## Install and verify locally

Verify the delivered SHA-256 checksum before executing the installer. An isolated
test prefix can be installed without configuring an external SQL server:

```sh
sh OUTPUT/myaivan-2026.10.09-candidate-r20-linux-x86_64.run \
  --prefix /tmp/myaivan-r20-test --tenant r20-test --isolated-sqlite --no-start
/tmp/myaivan-r20-test/myaivan verify
```

The production SQL configuration, explicit migration, startup and rollback
instructions are in `installer/README.md`. Do not treat a local install or service
health result as proof of an external channel or commercial workflow.

## Optional existing Gateway bridge and models

The complete delivery includes the verified r19 bridge tgz and its existing
Gateway reuse instructions. The six-service installer does not install a Gateway,
Node.js, a channel plugin, account credentials or a login flow. Reuse the existing
Gateway and its admitted channel/account configuration. Personal IM remains
manual-send/copy with confirmation; no automatic commercial reply is introduced.

The optional Chinese/English translation models and their licenses are separate
checksummed assets in the complete delivery. They are not embedded in the `.run`
file. Configure the existing verified cache or a compatible language provider
using the installer operations guide. Other languages depend on the configured
dynamic language provider.
