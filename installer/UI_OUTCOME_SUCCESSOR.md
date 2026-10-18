# Selected UI workflow successor

`build_ui_outcome_successor.py` creates a new private offline candidate from the
verified runtime-repair installer and an exact clean selected application tree.
It replaces only `src/aivan/app/static/app.js` and its necessary distribution and
root provenance records. All other payload bytes, including database repairs,
native dependencies, migration assets, controller and service configuration,
remain identical. The existing repair builder is unchanged.

```sh
python installer/build_ui_outcome_successor.py \
  --base-installer /absolute/path/to/selected-runtime-repair.run \
  --source /absolute/path/to/clean-selected-source \
  --revision FULL_COMMIT --tree FULL_TREE \
  --output /absolute/path/to/new-output --release RELEASE_NAME
```

The selected base checksum and application identity are fixed in the entry point.
Any extra runtime addition, removal, unrelated source change, dependency drift,
unsafe archive member, source/destination mismatch or unexpected output change is
rejected. A new release name is required; existing artifacts are never overwritten.
The selected source revision and retained base wheel/build identities are recorded
separately, including the preceding repair provenance.

This performs no installation, SQL connection/migration, service restart, model
call, channel action, listener change or public publication. It creates no account
or deployment requirement. Use existing operator-owned configuration and the
deployment owner's selection process. Build/inventory checks are not real MySQL,
API workflow, browser, live-channel or production acceptance. Native bytes are
unchanged, so prior ABI evidence is retained with that limitation, not rerun or
relabelled as a new host test.
