# Scoped integrated runtime repair build

`build_runtime_repair.py` creates a new offline candidate from the verified
integrated installer. It applies only the selected Aivan graph-label module and
the selected database canonical-language module. A database source mirror is
updated only if declared in the verified base inventory; no duplicate source
asset is invented when migrations import the installed package. Existing target
permissions are preserved, independent of checkout permissions. It does not
rebuild wheels or change native dependencies, migrations,
service bindings, authentication, channel configuration or unrelated components.

```sh
python installer/build_runtime_repair.py \
  --base-installer /absolute/path/to/verified-integrated.run \
  --source /absolute/path/to/clean-aivan \
  --revision FULL_CORE_SHA --tree FULL_CORE_TREE \
  --database-source /absolute/path/to/clean-database \
  --database-revision FULL_DB_SHA --database-tree FULL_DB_TREE \
  --output /absolute/path/to/new-output --release RELEASE_NAME
```

The database may alternatively use the existing full-tree source-manifest mode
through `--database-source-manifest`: the manifest must reconstruct the declared
Git tree and all required source blobs must match. This is explicit input
verification, not a fallback from a failed Git verification.

Use a new output name and enough staging space for the extracted payload and
compressed output. The builder rejects overwrite, source/inventory/lock drift,
unselected runtime additions/removals, unsafe archive entries and unexpected
payload changes. It verifies all source/destination hashes before replacement.
Both source identities and the base wheel provenance remain separately recorded
in the manifest, SBOM and distribution records.

All native bytes and their relative layout remain unchanged. The base ABI report
is retained with that limitation; the builder does not claim a new host/ABI run.
It performs no installation, service action, model invocation or business send.
Build/inventory success is not actual MySQL, API workflow, browser, public-route
or deployment acceptance. Run the applicable functional checks against the new
artifact before making those claims.
