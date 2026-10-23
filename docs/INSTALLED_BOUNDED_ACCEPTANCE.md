# Installed Aivan bounded HTTP acceptance

`scripts/verify_installed_business_workflow.py` retains its original `full`
mode, including its existing industry lifecycle assertions. The explicitly
selected `aivan-bounded` mode tests the shared inquiry, quotation and
human-authorized order-confirmation path without creating an industry buyer,
logging in to the industry application, or calling its production, QC,
shipment or sign-off APIs. It does not redefine either product's scope.

## Before running

Use only an authorized isolated installation and synthetic business data.
The operator must have already prepared the selected installation, MySQL
accounts, namespaces, migrations and two distinct synthetic tenants. This
runner does not install services, create SQL databases/accounts, migrate a
schema, alter cloud configuration or choose service ports.

The current profile uses the installation's bundled DB, GLTG and GPM APIs.
An existing configured language API may replace the bundled language service.
Other provider configurations remain outside this runner profile, not outside
the product. Likewise, this requested MySQL-specific deployment profile is not
a product-wide restriction on supported database vendors. SQL settings and
service credentials stay in the existing private
installation configuration; never pass credentials on the command line.

External email and OpenClaw business channels must be disabled for this synthetic
run. It exercises manual review and copy without attempting real delivery.
No receipt or result proves external delivery merely because approval succeeded.

Use the exact candidate package and the matching reviewed runner plus its
unchanged `installed_business_fixture.py` and `installed_email_acceptance.py`
helpers. Keep the three scripts together. The installed package inventory and
manifest are verified before execution. The runner's own hash is recorded
separately; a test-only runner revision does not relabel the installed package.

## Run

With the installation's bundled interpreter, in the same network namespace:

```sh
"$PREFIX/current/runtime/bin/python3" -B -I \
  /path/to/verification/verify_installed_business_workflow.py \
  --scope aivan-bounded \
  --prefix "$PREFIX" --package /path/to/verified-candidate.run \
  --evidence /path/to/new-empty-evidence-directory \
  --tenant EXISTING_SYNTHETIC_TENANT \
  --other-tenant ANOTHER_EXISTING_SYNTHETIC_TENANT \
  --run-id isolated-check-01 --synthetic-only --restart
```

Both tenant names must already exist in the selected installation. No arbitrary
tenant fallback is used. `--allow-test-identity-fixtures` is not required for
this mode because it does not provision a buyer account. `--restart` explicitly
authorizes the selected installation's managed restart; it is required for this
complete recovery scenario. Do not run it against production without the
applicable operational authorization.

Omitting `--scope` preserves the existing full mode and its original explicit
buyer-fixture permission. Mixed-source diagnosis and the email-recorder scenario
remain separate full-mode options; the bounded mode cannot silently claim them.

## Executed scope and evidence

The bounded path verifies:

- Metadata-only MySQL identity checks for Aivan and the private-data provider,
  using the package-verified configuration helper. It does not read or change
  industry business tables or scan unrelated historical databases.
- Missing, wrong and raw non-ASCII credentials; actual configured tenant
  propagation and bidirectional supplier/case isolation.
- Dynamic non-English intake, human clarification, idempotent replay/conflict,
  provider graph readback and real supplier inquiry drafts pending review.
- Supplier reply, GLTG/GPM-dependent recommendation, rejection without delivery,
  the existing `/invoke` case-revision path and a regenerated quote requiring
  fresh review. The revised synthetic quote explicitly states USD 8.75 and
  30.5 production days; the returned supplier declaration must retain that
  fraction, and returned GLTG quantiles must remain finite, nonnegative and
  monotone. These are input/returned-result checks, not a local GLTG engine.
  Rejected history must remain rejected and unsent.
- Bound preview/copy/approval, premature or rejected order denial, authorized
  synthetic order confirmation and the same provider order on replay/readback.
- File/image API handling, selected canonical English API readback, audit and
  Markdown export. A failed independent check remains an overall failure.
- Restart of the selected installation, unchanged candidate identity, fresh
  authenticated clients using the recorded current ports, and durable order,
  rejected-draft, guidance and attachment readback without industry writes.
  The full installed-file verifier must succeed again after restart; an unchanged
  manifest alone is insufficient. Guidance must match its packet, tenant and
  case, contain recommendation/model output/lineage, and equal the complete
  pre-restart snapshot. The rejected draft must explicitly retain a null
  `sent_at` and have no relay receipt in the case before and after restart.

The run records actual package/runner/helper/component identities, HTTP statuses
and response digests. Unexpected HTTP responses and transport failures are not
printed as raw remote text or credentials. Private service logs remain private.

This is backend HTTP/MySQL acceptance when actually executed against the
prepared services. Synthetic unit/MockTransport tests of the runner are only
unit/contract evidence. They are not CTYun integration, browser acceptance, the
five-run web checks, live email delivery, industry execution, production
deployment or release approval. None is claimed by adding this mode.
