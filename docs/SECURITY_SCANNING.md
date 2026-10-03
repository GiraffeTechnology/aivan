# Repository security scans

This repository runs license-available local scanners instead of the unavailable
GitHub CodeQL and GitHub Dependency Review services. These are **different,
bounded scans, not equivalent CodeQL security-extended coverage**. They do not
require GitHub Advanced Security, an organization plan change, a Semgrep account,
or SARIF ingestion by GitHub. Existing Bandit and `npm audit --audit-level=low`
gates remain unchanged.

## Tools and rule provenance

| Scanner | Pinned version | License | Purpose |
| --- | --- | --- | --- |
| [Semgrep Community Edition](https://github.com/semgrep/semgrep/tree/v1.179.0) | 1.179.0 | LGPL-2.1 | Source-pattern security checks |
| [OSV Scanner](https://github.com/google/osv-scanner/releases/tag/v2.6.0) | 2.6.0 | Apache-2.0 | Known dependency vulnerabilities |
| [zizmor](https://github.com/zizmorcore/zizmor/releases/tag/v1.30.1) | 1.30.1 | MIT | GitHub Actions security checks |

Semgrep uses only the vendored, MIT-licensed Python and JavaScript rules from
[patched-codes/semgrep-rules at 1118d79823ae756534678378a4aac0cbfa5d3041](https://github.com/patched-codes/semgrep-rules/tree/1118d79823ae756534678378a4aac0cbfa5d3041).
The 79 upstream YAML files are unmodified: 69 declare Python, 10 JavaScript, and
9 explicitly also declare TypeScript. Semgrep additionally applies compatible
JavaScript rules to TypeScript. Each original GitLab MIT copyright header and
the upstream MIT LICENSE are preserved. `tools/security/semgrep/manifest.json`
records the source, revision, rule inventory and SHA-256 of every file; CI checks
each digest before scanning. No Semgrep Registry rules or separately licensed
Semgrep commercial rules are downloaded. The upstream snapshot dates to 2024;
it is reviewed, pinned coverage, not a claim of current complete vulnerability
research.

The Linux amd64 OSV release binary is verified against SHA-256
`ca69b3d3cd08f889a49dc0a383122f71cc528b83803671df5fd874d97485b108`
from the v2.6.0 release. Python scanner package versions are pinned in
`tools/security/requirements.txt`; their transitive package dependencies are
resolved by pip. GitHub Actions dependencies use commit pins.

## Coverage and failure behavior

- **Semgrep:** All Git-tracked `.py`, `.pyi`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`,
  `.tsx`, `.mts`, and `.cts` files, including tests and committed generated code,
  are explicit inputs. No blanket test/script exclusion or inline `nosem`
  suppression is honored. The actual scanned-path set must equal the complete
  inventory, and the report must contain all 79 rule definitions. WARNING and
  ERROR findings block. INFO findings remain visible in raw reports and counts;
  they do not block. Existing INFO observations are mostly test assertions.
  Every scan uses `--error --strict --oss-only`, with per-rule/file timeouts.
  Reported parse errors, skipped rules, unexpected exit statuses, missing/invalid reports,
  timeouts, empty target sets and incomplete target/rule coverage fail the job.
- **Dependencies:** OSV scans every tracked `uv.lock` and `package-lock.json`,
  including development dependencies. This is a full resolved-lockfile scan,
  rather than GitHub Dependency Review's pull-request dependency delta. Both
  ecosystems must be present and nonempty. `--all-packages --all-vulns` reports
  the full inventory and findings; the wrapper verifies every registry package
  and version from each lockfile is represented. No vulnerability ignores are
  configured. Any advisory finding or scanner error fails. Matching uses
  `--offline`: no package identity/version, source or credential is sent to an
  external vulnerability service. Before scanning, CI downloads the complete
  public PyPI and npm database archives from fixed URLs; the downloads contain
  no project-specific query parameters or request payload.
- **GitHub Actions:** Every tracked workflow and `action.yml`/`action.yaml` is
  scanned individually by zizmor, using offline regular-persona audits and strict
  parsing. No inline or incidental configuration ignores are honored. Every
  input must have a successful SARIF invocation. All unreviewed findings fail;
  the wrapper reads findings because zizmor's SARIF mode returns zero even when
  findings exist. Offline mode intentionally excludes network-dependent audits.

The required CI context named **Dependency review** is retained for compatibility
with the repository ruleset. Its implementation and step names explicitly use
OSV; it does not call or claim to be the GitHub Dependency Review service.
Semgrep and zizmor have separately named checks. No repository security settings
or branch rulesets are changed by this migration.

Each job uploads `security-reports/<scanner>/` with `if: always()`, retaining raw
JSON/SARIF, command/exit logs, expected inventories, coverage counts and a final
status. Missing artifacts fail upload. Reports are retained for 30 days. A
successful check means its configured checks completed and its blocking policy
passed; it does not mean there are no INFO or reviewed findings.

## Fully offline dependency matching

OSV Scanner 2.6.0's `--offline` sets offline vulnerability matching and disables
network-dependent plugins and transitive resolution. `--offline-vulnerabilities`
alone is **not** used as a privacy guarantee. See the pinned
[flag implementation](https://github.com/google/osv-scanner/blob/v2.6.0/cmd/osv-scanner/internal/helper/flags.go)
and [plugin selection](https://github.com/google/osv-scanner/blob/v2.6.0/pkg/osvscanner/scan.go).

The CI download step retrieves only these complete public datasets:

- `https://osv-vulnerabilities.storage.googleapis.com/PyPI/all.zip`
- `https://osv-vulnerabilities.storage.googleapis.com/npm/all.zip`

There is no online-query fallback. OSV 2.6.0 uses its pinned `osv-scalibr` matcher
cache, under `$OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY/osv-scalibr/<ecosystem>/all.zip`.
Both archives are fetched anew for each dependency-review run. Missing or invalid
archives fail before scanning. The wrapper verifies response content length,
ZIP integrity, every advisory record, and a nonempty inventory. A small helper
uses the same `protojson.Unmarshal` decoder and exact schema/protobuf module
versions as OSV 2.6.0 to reject any record that OSV would silently skip while
loading. It does not add CVSS-format, Git-hash-format, or other advisory semantic
lint. Historical metadata accepted by the real decoder remains accepted.

The helper uses Go 1.25.8, schema module
`v0.0.0-20260902031056-b388a18021a3`, and protobuf `v1.36.12`, pinned with `go.sum`.
Only these public tool dependencies are fetched during its build; the built helper
performs no network operations. Tests exercise malformed field types, dates,
unknown/duplicate fields, and accepted historical-format metadata. No product
Go dependency or new product acceptance condition is introduced.

Reports retain response headers (including upstream modification time and
object generation), retrieval verification time, SHA-256, byte sizes and record
counts. These hashes identify the exact database snapshot; they are not a claim
of a separately signed upstream SHA-256 digest. The 2026-10-02 validation snapshot
contained 26,005 PyPI records and 229,789 npm records, approximately 241 MiB
compressed in total. Database content and known-advisory results evolve.
Public advisories retain their individual upstream attribution and licenses;
see [OSV data licensing](https://google.github.io/osv.dev/data/).

A separate public-fixture test ran the real pinned scanner under a process-only
seccomp filter that traps network syscalls, including socket/connect/send/recv.
The network positive control failed with SIGSYS, while the offline scan completed
normally and detected 53 advisories for known-vulnerable Django/lodash fixtures.
This demonstrates no network-syscall attempt in that tested scan; CI relies on
the same pinned scanner's explicit offline configuration. No persistent host
network or security settings were changed. Private-repository online queries
are not part of this workflow.

## Narrow reviewed findings

`tools/security/reviewed-findings.json` contains exact rule + path + whole-file
SHA-256 + finding-count exceptions, with reasons. Raw findings are retained and
reported separately. Changed content, a changed matching count, or any unrelated
finding cannot inherit an exception.

- Two Python smoke scripts call `urllib.request.urlopen` against operator-selected
  test/API destinations or fixed localhost URLs, with explicit timeouts. Their
  URL inputs are not application request input. The generic urllib rule matches
  all such uses. These exact two files account for two and three findings.
- Eight web-only JavaScript runtime tests contain twelve exact filesystem reads
  of literal application source/template URLs resolved from `import.meta.url`.
  Inquiry, conversation, upload and clipboard fixtures never control those paths.
  Each reviewed rule/path is bound to its own whole-file digest and exact count,
  not a blanket test exclusion. The GPM smoke-script review was refreshed after
  synthetic request fields changed; its three operator-selected/localhost URL
  destinations and explicit timeouts are unchanged. Scanner reports retain all
  seventeen WARNING findings (five urllib calls and twelve source-file reads).
  Content drift, a new matching occurrence, or an unrelated rule still fails.
- The main-only `myaivan-direction-policy.yml` uses `pull_request_target` to keep
  its direction guard owned by the base branch. It reads metadata with a read-only
  token, does not check out or execute PR code, and passes untrusted metadata via
  environment variables. Its single dangerous-trigger heuristic is reviewed for
  that exact content. Changing it to `pull_request` would weaken tamper resistance.

The INFO-severity `assert` observations also include six `self._db is not None`
checks in the main branch's `packet_store` methods (`save`, `get`, `update_status`,
`write_audit`, `list_by_tenant`, and `decide`), and five analogous checks on the web
branch. These were reviewed individually: each is inside `if self._durable`;
construction sets durable mode only after receiving a non-null adapter and a
successful schema probe, and these fields do not subsequently change. Tenant
filtering, principal authorization, production fail-closed behavior, decision
validation, and atomic proof checks use ordinary conditionals/calls. Running with
Python `-O` does not remove those boundaries. INFO findings are still retained;
this review is not a blanket claim that security assertions are safe.

These are code-reviewed false-positive treatments, not an advisory baseline or
permission to hide newly discovered vulnerabilities. Fixed shared `/tmp` paths
in two local simulation/reproduction scripts are repaired with private temporary
directories rather than exempted.

## Limits and maintenance

Semgrep CE's pattern matching and intraprocedural analysis do not replace
CodeQL's query set, whole-program/dataflow behavior, or GitHub's code-scanning UI.
Parser recovery/prefiltering can tolerate some invalid syntax without emitting an
error; the existing compile checks and tests remain the syntax-validity gates.
Rules do not cover every vulnerability class or library. Inline code embedded
inside HTML, YAML, shell or strings is outside the listed source-extension
inventory; zizmor checks Actions semantics, not arbitrary embedded application
code. Current application HTML uses external script files that are included.
Dependency scans find known published advisories, not unknown vulnerabilities;
OSV does not provide GitHub Dependency Review's dependency-change/license-policy
UI. No dependency license allowlist is introduced.

Update scanner versions and rule snapshots in a reviewed change, retaining
license notices and regenerating/verifying digests. Re-run positive and negative
controls after updates. Do not claim that merely increasing rule/file counts
establishes equivalent coverage.

Local usage, after installing the pinned tools:

```sh
python tools/security/scan.py semgrep
python tools/security/scan.py osv
python tools/security/scan.py zizmor
```

Tests use temporary fixtures outside the product tree: safe Python/JavaScript/
TypeScript pass; expression evaluation in each language and an ERROR-severity
insecure temporary-file example fail; INFO remains visible without blocking;
malformed source/rules and missing tracked sources fail; vulnerable npm and Python
locks fail; safe locks pass; Actions title interpolation fails while a safe
workflow passes; malformed workflows fail. Exact results belong to the change's
validation evidence, not production features.
