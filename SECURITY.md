# Security Policy — AIVAN

## No credential storage

AIVAN does not store, log, or transmit:
- Marketplace account passwords or session tokens (Alibaba, AliExpress, Wangwang, etc.)
- IM platform credentials or cookies
- LLM API keys (read from `.env` at startup; never written to the database or logs)
- OpenClaw account secrets

Marketplace and IM account management is delegated entirely to OpenClaw. AIVAN holds only the normalised event data that OpenClaw sends it.

## Human approval gate (non-negotiable)

Every outbound message produced by AIVAN is stored as a pending draft. No message is sent to any buyer, supplier, or platform until a human operator explicitly approves it via the AIVAN dashboard or API. This gate cannot be disabled.

## No bypassing platform rules

AIVAN does not:
- Bypass CAPTCHA, login flows, or access controls on any platform
- Circumvent rate limits imposed by marketplaces or IM platforms
- Scrape or access marketplace data through undocumented means
- Impersonate users or automated accounts

## Private-domain data and service boundary

The chosen private-domain DB (`giraffe-db` or a compatible replacement) is the system of record for business history and process state. A compatible local SQLite profile may be used; it is not the only permitted database or a reason to make chat context authoritative.

Explicitly configured DB, GLTG, GPM, language and connectivity APIs may process the minimum data needed for their authorized function. Approved dependency processing is distinct from sending an external business message, which still requires human authorization. Do not claim that no data can leave the device when remote dependencies are configured.

Standard English is the work/interaction language. Non-English input/output uses dynamic `giraffe-language-skill` translation before workflow or for requested display. Except enterprise/user profiles, stored textual business content is standard English; raw-message/audit/metadata copies are not exceptions. Safe file/image input remains supported.

The two designated simulated DBs are valid for functional acceptance through real application/API execution. Keep data labels, authentication, tenant/object isolation, durable writes/readback, safe storage and truthful outcomes. No simulated dataset authorizes fabricated facts or skipped checks.

## External LLM keys are optional

The default LLM provider is `mock`, which requires no external API keys and makes no network calls. If an external provider is configured, keys are read from `.env` and passed only to the configured provider's API. Keys are never logged or stored in the database.

## Risk screening is decision support only

AIVAN's supplier risk reports are automated decision-support outputs. They are not authoritative legal, compliance, sanctions, or credit decisions. Every risk report includes the disclaimer:

> "Absence of negative evidence is NOT proof of safety. This report is for human review only."

## AIVAN does not make legal, credit, sanctions, or compliance decisions

AIVAN does not make binding legal, credit, sanctions, or compliance decisions. All outputs — supplier options, risk ratings, quotes, lead-time estimates — are drafts and recommendations for human review. No action is taken without explicit operator approval.

## Supported versions

Security fixes are provided for the latest commit on `main`. Released versions older than the current release are not currently supported.

## Reporting vulnerabilities

Use GitHub's **Report a vulnerability** form on the repository Security tab. Do not open a public issue and do not include credentials, customer data, prompts, supplier records, or production logs in a public discussion.

Please include the affected commit or version, reproduction steps, impact, and any suggested mitigation. The maintainers aim to acknowledge a report within 3 business days and provide an initial assessment within 7 business days. Coordinated disclosure should wait until a fix or mitigation is available.

If private vulnerability reporting is unavailable, contact the Giraffe Technology maintainers through a previously verified private channel and request a secure reporting route.

## Security boundaries

AIVAN may make outbound connections to explicitly configured services including OpenClaw, Ollama or an approved external LLM provider, the configured email adapter, GLTG, GPM, giraffe-language-skill and the selected private-domain DB. Operators are responsible for configuring authentication, network allow-lists, TLS, retention, and least-privilege credentials for those services.

Security claims in this document are enforced by automated tests where practical, but deployments must also validate environment variables, reverse-proxy timeouts, database permissions, and external-service configuration.

