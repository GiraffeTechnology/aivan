# MyAivan Web Requirements

Reconciled: 2026-10-02. Scope: the first usable web version of Aivan, within the [Aivan product definition](AIVAN_PRODUCT_PRD.md). This is a delivery target, not a claim that the current UI implements it.

## 1. Purpose and relationship

MyAivan is the user-facing web version of Aivan, the Giraffe Agent frontend for inquiry, quotation and order confirmation. The first web iteration provides a simple conversation workflow for receiving trade information, preparing outbound drafts, human review, manual IM handling, controlled email and case backup. It is not a separate CRM, mailbox, IM aggregator or monitoring-only business system.

`myaivan-web` remains its permanent release branch. Web implementation PRs target that branch; never merge it into `main`. Shared product facts and business state remain consistent across entry points. Release separation does not justify duplicate authoritative Case/Draft/Approval/Order state machines.

## 2. Required user experience

### Welcome and entry

After the applicable login or clearly identified demo entry, display:

> Welcome back. What should your AIVAN handle today?

The **Start Working** button opens the conversation page. The primary entry is `myaivan.com`; a document is not evidence that the public route is deployed.

### Conversation page

Use a vertical three-area layout:

1. **Top: conversation stream.** User messages align right and Aivan messages left. Show text, pasted external messages, file/image cards, extracted facts, missing-field questions, suggestions and accurate status events.
2. **Middle: generated outbound review.** Keep draft review visibly separate from conversation. Display channel, recipient, purpose, subject where relevant, body, risk notes and the actions below.
3. **Bottom: input.** Text, Paste, file upload, image upload, voice button or honest disabled placeholder, and Send.

Supporting case/history, audit and health views may be retained. They must not replace this user workflow with an operations dashboard.

### Draft actions

- **Copy for manual paste:** copy the actual draft body; record a copy event without claiming delivery.
- **Send by Email:** show recipient/subject/body confirmation, then call the configured OpenClaw-Aivan adapter only after confirmation.
- **Mark as manually sent:** record the user's confirmation that the message was actually sent outside Aivan, with the relevant case/draft/channel. This does not become a provider delivery receipt.
- **Reject draft:** mark it rejected and unsent; ask for changes or allow regeneration. Preserve its history and the revised draft's relationship.

Risk notes call out prices, delivery dates, lead times, payment terms, quality promises, order confirmation, compensation and binding commitments. Rendering or approving a draft alone must never imply it was sent.

## 3. Required flows

### Receive and understand

The user types or pastes a buyer inquiry, supplier reply or instruction. Aivan shows the message and a structured summary, identifies relevant missing fields, and prepares an appropriate reply draft when requested or when it is the clear next step. Facts come from the configured private-domain DB and newly recorded source evidence; chat history is not fact authority.

### Manual IM reply

For WeChat, WhatsApp, LINE and Wangwang: generate the channel-appropriate message, review it, copy it, manually send it in the external application, then mark it manually sent. The web iteration neither implements nor claims direct IM sending.

### Email

Show the provider state as configured, not configured or mock. A configured attempt uses OpenClaw-Aivan after explicit confirmation and records the actual result. An unavailable provider displays: “Email sending is not configured. Please copy the draft manually.” A mock attempt stays visibly simulated. A timeout or uncertain result does not become `email_sent`, and a retry must not create duplicate delivery.

### Rejection and revision

Reject without any outbound side effect. Record the rejection, accept revision instructions and display the revised draft for a fresh review.

### File and image input

File and image upload are usable first-iteration features. A selected supported file/image appears in the conversation with its name, stored reference and available preview. Aivan provides a grounded summary and can draft a reply or follow-up from the supported content; inability to parse must be explicit, not a fabricated summary. Record attachment ownership and case linkage.

Use the simplest safe storage compatible with the DB-backed workflow. Enforce appropriate access, type/size validation and safe rendering. A particular object-storage product or an entire scanning platform is not a source-defined prerequisite. Do not postpone file/image input by calling it a voice-style placeholder. Voice transcription may be deferred; the microphone control must clearly say it is unavailable and never fake transcription.

### Backup and resume

**Backup Case** exports Markdown containing the case title/status/timestamps, messages, attachment names, draft versions and copy/send/reject statuses, and audit history. JSON is optional; PDF is later work. Export is not a substitute for database persistence. A user can reopen a case after changing conversations or restarting and recover its business state from the DB.

### Order confirmation in the full product

The web version uses Aivan's shared inquiry-to-quotation-to-order-confirmation business model. A full-flow delivery includes a human-confirmed selected quotation and persisted order state. The original first UI acceptance covers the receive/draft/review/communication/backup loop; it must be reported at that scope rather than falsely called the whole product complete. No separate formal-contract signature or version gate is added.

## 4. State and data

Use a lightweight case-oriented view over the shared DB-backed business model. Standard English is the work/interaction language. Dynamically translate non-English input with `giraffe-language-skill` before workflow and requested non-English output through the same module. Except enterprise/user profile information, all stored textual business content is standard English; raw messages, audit text, attachments and metadata do not create exceptions. Retain permitted source references/hashes and canonical English, not a new non-English side store. Logical records include:

- Case: ID, title, business status, timestamps, source/target channel, linked messages/drafts/attachments/audit and order references when applicable.
- Message: ID, case, user/Aivan/system role, type, content or durable content reference, source metadata and timestamp.
- Draft: ID, case, version, channel, recipient/subject/body, risk notes, created/updated times and actual review/delivery status.
- Attachment: ID, owning tenant/case, standard-English display name or non-linguistic source reference, validated type/size, safe storage reference and processing status.
- Audit: actor, case/draft/object, event, result, time and source/correlation reference without secrets.

Preserve distinctions such as draft, copied, rejected, failed, confirmed email outcome and manually sent. Keep approval, provider acceptance/delivery evidence and human relay confirmation distinct even where the existing API uses different enum names.

The later product-owner DB ruling supersedes browser-only business persistence in the original web brief. Cases, facts and process changes are written through the selected DB contract and recovered from it. localStorage can hold non-authoritative UI preferences/cache; it cannot replace the DB. SQLite or another simple durable provider is acceptable when it satisfies the selected contract. Do not require a complex migration solely because the UI is being delivered.

The designated two simulated databases are valid acceptance sources. Real selected application/API paths must run against them; fake service responses and skipped work are not accepted as integration evidence.


The DB text-language rule does not prohibit non-English file/image input or require rewriting image pixels. Translate extracted business text through the language module before workflow and storage. File references and binary inputs follow the selected safe storage/authorization boundary; they do not justify retaining prohibited raw business text in DB fields or an evasion side store.

## 5. Implementation boundaries

Use the existing stack unless there is a concrete reason to change it. Framework choice is not product identity. Retain working authentication, trusted actor/tenant context, shared Core services, audit and useful assets. The browser must not persist platform credentials or production API secrets.

GLTG and GPM remain API dependencies for functions using their outputs. The DB is the facts/process system of record. OpenClaw-Aivan is the IM/email access dependency. A dashboard, a connected channel, or a successful mock demo does not replace the specified conversation and review workflow.

## 6. First-iteration acceptance

Run all applicable first-iteration cases five consecutive times against the same candidate; fix failures and restart the sequence. Record the individual runs, failures and environment. The original 20 cases remain:

1. Welcome page renders.
2. Start Working navigates to the conversation.
3. Conversation page renders the three areas.
4. User messages align right.
5. Aivan messages align left.
6. Paste works, or clipboard denial offers Ctrl+V/Cmd+V fallback.
7. File upload works for a supported file.
8. Image upload works for a supported image.
9. Voice control is usable or safely disabled without breaking the UI.
10. Generated draft appears in the review area.
11. Copy copies the draft body.
12. Manual-send confirmation records the correct status.
13. Reject records rejection and allows revision/regeneration.
14. Email action invokes the adapter only after explicit confirmation.
15. Unconfigured/failed/mock email is handled honestly with manual-copy fallback.
16. Backup exports Markdown.
17. Audit records copy/send/reject actions accurately.
18. No direct IM send is implemented or claimed by this iteration.
19. UI positioning does not describe a generic chatbot.
20. Product copy preserves Aivan's digital trade assistant role.

Also verify the later DB requirement on the selected workflow: writes/readback, conversation switch/restart recovery, correct case/tenant isolation and no fabricated success on provider failure. These checks implement the explicit data-truth ruling; they do not require production-customer data.

Unconfigured email is an accepted fallback state for this UI scope, not proof that real email delivery passed. Live email acceptance, when claimed, requires an actual authorized attempt and result. Full Aivan order-confirmation acceptance follows [the shared criteria](ACCEPTANCE_CRITERIA.md). Deployment, broader operational work and abcdYi's complete lifecycle must be reported separately from these UI results.
