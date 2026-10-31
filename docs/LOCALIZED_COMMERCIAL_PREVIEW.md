# Localized commercial preview and delivery

The authenticated draft preview endpoint renders the final recipient-facing text
before human approval. MyAivan shows the sender, recipient, target language and
body. Approval submits an opaque preview identifier, never a client-supplied body.
The server binds that preview to the draft, tenant, case, channel account,
recipient, sender configuration, English source, target language and render digest.
Changes invalidate approval. The source fingerprint and append-only audit identity
supply the source/version binding without storing a second business document.

English drafts pass through unchanged. Other languages use the existing shared
language provider. Missing configuration or a translation failure leaves review
pending. Tests use an explicitly synthetic translator; they do not establish real
translation-model quality or deployed provider acceptance.

Only the English canonical draft and language/digest/identity metadata are durable.
Localized bodies are transient API responses or memory. They are not stored in
draft, approval, audit, receipt or browser storage. A restart re-renders and checks
the approved digest. A changed translation requires human review again.

MyAivan web IM previews use guided manual copying and a human receipt. A copy is
not an API send. The low-level adapter capabilities and non-web entry points retain
their existing channel policy and explicit approval checks. The copy and receipt
records bind the reviewed preview and digest without retaining localized text.

Before an adapter or SMTP attempt, the approved identity is atomically claimed
and committed as `delivery_unconfirmed`. Explicit success records `sent`; a
confirmed rejection records `send_failed`. Timeout, malformed acknowledgement,
connection loss after submission or process interruption leaves the durable
unconfirmed state. Approval, preview and retry endpoints do not resend it. An
operator must reconcile the actual provider receipt before any separate recovery
action; this change does not invent exactly-once transport or a reconciliation API.

Validation includes English and synthetic French preview/approval, changed
source/recipient/sender/translation, unavailable translation, manual IM receipt,
all local SQL text-cell scans, SQLite restart, lost acknowledgement, process
interruption, SMTP failure injection and browser-runtime DOM/clipboard tests.
The tests send no commercial messages. Real browser/device and configured
translation/transport provider acceptance remain deployment work.
