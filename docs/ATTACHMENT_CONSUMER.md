# Case attachments

Supported intake is UTF-8 plain text (64 KiB maximum) and PNG/JPEG images
(10 MiB maximum, 16 million pixels). Open a case already saved through the
selected data provider before uploading. Images are stored and can be previewed;
no OCR or extracted summary is claimed. Plain text is normalized through the
configured language skill before persistence and is returned as canonical English.

The authenticated web API uses:

- `POST /api/workbench/cases/{case_id}/attachments`: closed JSON fields
  `file_name`, `content_type`, `content_base64`, `sha256`; session CSRF and
  an explicit `Idempotency-Key` are required.
- `GET /api/workbench/cases/{case_id}/attachments`: verified provider metadata.
- `GET /api/workbench/cases/{case_id}/attachments/{attachment_id}/content`:
  authorized bytes, integrity verified against provider metadata.

The consumer requires `GIRAFFE_DB_BASE_URL` and the service credential in
`GIRAFFE_DB_SERVICE_AUTH_SECRET`, supplied by the authorized configuration store.
It propagates the authenticated tenant, not a caller-selected body tenant.
The selected provider must implement attachment create/metadata/content and
the case transaction graph's `attachments` collection. No local binary store
or direct provider-table access is introduced.

Success requires provider readback. Unknown write outcomes stay unknown;
retry the same operation with the same key. Provider denial, conflict and invalid
input remain distinct. Case backup reads attachment names from the provider;
unavailable provider history is not represented as an empty verified list.

Images use authenticated downloads and integrity-checked browser Blob previews.
Only the image CSP directive permits Blob URLs; scripts, objects and frames
remain restricted. Conversation switches dispose preview URLs.

Local HTTP tests execute real provider migrations and process restart against
an isolated SQLite database. They do not prove CTYun/MySQL migration compatibility,
the complete inquiry workflow, deployed image preview, or public availability.
