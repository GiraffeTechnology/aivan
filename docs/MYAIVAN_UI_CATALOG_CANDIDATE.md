# myAIVAN UI catalog candidate evidence

This document records the application-side acceptance boundary for the myAIVAN permanent branch. It does not authorize or describe server, DNS, TLS, proxy, port, process, database, bridge, or cloud-control changes.

## Candidate lineage

- Permanent destination branch: `myaivan-web` only. These product files must never merge to `main`.
- Withdrawn baseline: commit `0747e79a8dd4ea4f1f6405f72db9ba82fe97ff89`, tree `eb76907b0380f66fbb2fb412afdb0250d608477f`.
- A new full commit SHA and tree are recorded in the immutable build evidence after the candidate commit exists. The withdrawn baseline is never a production candidate.

## UI catalog contract

- The Python catalog in `src/aivan/app/ui_catalog.py` is the versioned authoritative English source. Stable message IDs are independent of their English values; any value or key-set change rotates `catalog_version`.
- FR, ES, DE, KO, and JA are generated only through `giraffe-language-skill`. qwen3.5:9b is accepted only as `proofread-only`, never as provider, generator, backend, or translator fallback.
- Generated catalogs are candidate-bound, complete-key-set, fixed-input, read-only artifacts. The public API never accepts source text and never triggers translation.
- Catalog files and directories must be absolute, non-symlink, private on POSIX, safely opened and atomically replaced. Artifact SHA-256 is emitted by the generator.
- `/readyz` fails closed until all five generated locales match the active candidate, catalog version, policy, provider/model/backend, message set, and per-message provenance.
- The browser forces English-manifest revalidation across deployment switches, rejects an old candidate, loads generated languages before authentication, caches one promise per locale, ignores late responses for inactive locales, and renders generated values only through text or escaped HTML paths.

## Giraffe Technology VI input

- Authority: `Giraffe_Technology_VI_Guidelines_CN_v1.2.pdf`, Version 1.2 / 2026, 23 pages.
- SHA-256: `dcbc6b2e81572b474baa6922deb392785f126ce8d844409e09e0f2fe4b9f3e97`.
- Implemented application rules include the approved palette (`#FCB13C`, `#D6720E`, `#080808`, `#FFFFFF`), Noto Sans CJK-first UI typography, 12-column/large-margin/left-aligned layout, and single-focus treatment. The 40px independent-mark/white-circle and 140px combination-mark rules remain acceptance checks for a future approved master.

### Approved-PDF-derived raster provenance

The authoritative PDF contains no independent vector `/Form` logo object, so the project does not claim an original SVG/vector master. The approved standard pages do contain lossless RGB `/Image` XObjects with `/SMask`. The independently verified delivery reconstructs those objects as transparent PNG without screenshots, OCR, vectorization, generative redraw, or cross-brand assets.

- Delivery ZIP: `giraffe-vi-v1.2-approved-pdf-derived-raster-assets.zip`, 1,242,218 bytes, SHA-256 `91FA47AC57DE5E77D745A0479C812417CE62D1EAC5079D81DD0669E48CD515D9`.
- Web asset: `giraffe-logo-graphic-mark-approved-pdf-derived.png`, 615×802, 271,382 bytes, SHA-256 `DFD19B25AE703DD1F4584CC255D822A26A967BE3100EB2C94202CCC541724E4F`.
- Traceability manifest: `docs/brand/giraffe-vi-v1.2-approved-pdf-derived-raster-manifest.json`, repository copy SHA-256 `0131A4C0564A5E2AFC3ACC3CE66BF17B618C4646C3264A501E687A81C2DA71E1`.

The UI renders the independent mark without distortion inside a white, strictly circular base. The approved mark is at least 40px high in the header and 52px on the login screen. ArtCCH, the QC icon, JINÉ/NÉSHA, old Stage 3 UI, `giraffe-icon-tight.png`, screenshots, and JPG sources are excluded. This asset may be called an **approved-PDF-derived raster asset**, never an original vector master; unlimited scaling/print editing still requires brand-owner SVG/AI/EPS/vector-PDF delivery.

## Production acceptance gates

Application completion requires a clean new candidate SHA/tree, full CI and CodeQL, independent Aivan P0/P1=0 review, five real non-fallback translator catalogs, and public desktop/mobile A–K acceptance. Server-side deployment and fault handling remain exclusively with the `全服务器` task. No real business message may be sent during acceptance, and the dedicated test entry must be disabled afterward.
