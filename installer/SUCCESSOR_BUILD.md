# Build the reviewed three-file Aivan successor offline

`build_successor.py` is separate from the historical fixed r18/r20 builder.
It uses the verified r20 installer as an immutable runtime dependency source,
then replaces exactly the reviewed Aivan files: `workbench_routes.py`,
`app/static/app.js`, and `integrations/giraffe_db.py`. All other Aivan runtime
files must match the original payload source inventory. The source must be a
clean Git checkout at the full commit/tree provided in the release handoff.

Use Linux x86_64, Python 3.12 or later, Git, readelf and ldd. Reuse existing
runtime assets; this entry does not install or download dependencies.

```sh
unshare --net python3 CANDIDATE/installer/build_successor.py \
  --base-installer R20/myaivan-2026.10.09-candidate-r20-linux-x86_64.run \
  --source CANDIDATE --revision FULL_COMMIT --tree FULL_TREE \
  --release RELEASE_NAME --output NEW_OUTPUT_DIRECTORY
```

The builder verifies the frozen installer/payload inventory and dependency lock,
checks the exact runtime delta, updates the installed distribution RECORD and
derived provenance, and emits updated SBOM, component/source/payload manifests,
archive checksum and a complete installer. Original wheel and dependency
identities remain historical base evidence, not newly built distributions.
Offline imports and ELF dependency checks execute before installer emission.

The command above is an invocation template, not evidence that a full build has
already run. Unit tests of the builder do not prove a full package build. Record
the actual command, exact candidate and all output checksums when it is run.
Retain r20 unchanged and do not overwrite an existing release installer.

Build completion is not deployment or workflow acceptance. The application/UI
deployment owner must validate configuration references, real MySQL API
write/readback and recovery, language/OpenClaw integration, and actual browser
actions using the selected complete candidate. Preserve existing manual-send
and human-review boundaries. Do not configure a replacement SQLite deployment
or restart production as a side effect of building.
