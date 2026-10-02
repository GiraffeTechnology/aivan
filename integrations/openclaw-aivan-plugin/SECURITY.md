# Security Policy — @giraffetechnology/openclaw-aivan

## No credential storage

This plugin does not store, log, or transmit:
- OpenClaw account passwords or session tokens
- Marketplace account credentials (Alibaba, AliExpress, Wangwang, etc.)
- IM platform tokens or cookies
- LLM API keys
- Any other secrets

The plugin only holds `AIVAN_BASE_URL` (a localhost URL) and an optional `AIVAN_API_KEY` bearer token that is read from the environment at runtime and never persisted.

AIVAN itself delegates all IM, email, and marketplace account management to OpenClaw. AIVAN never stores platform passwords, cookies, or session tokens.

## No outbound message without human approval

Every outbound message drafted by AIVAN requires explicit human approval before it is sent. This plugin cannot bypass that gate. Calling `aivan.approveDraft` forwards the approval request to the AIVAN local API, which enforces the policy. The plugin has no direct access to OpenClaw send channels.

## No bypassing anti-bot or platform rules

This plugin does not:
- Bypass CAPTCHA, login flows, or access controls on any platform
- Circumvent rate limits imposed by marketplaces or IM platforms
- Access platform data through undocumented or unofficial means
- Perform web scraping outside of officially sanctioned integrations

All marketplace and IM operations route through OpenClaw's documented channel SDK.

## Private-domain data and service boundary

The chosen private-domain DB (`giraffe-db` or a compatible replacement) is the system of record for business history and process state. A compatible local SQLite profile may be used; it is not the only permitted database or a reason to make chat context authoritative.

Explicitly configured DB, GLTG, GPM, language and connectivity APIs may process the minimum data needed for their authorized function. Approved dependency processing is distinct from sending an external business message, which still requires human authorization. Do not claim that no data can leave the device when remote dependencies are configured.

Standard English is the work/interaction language. Non-English input/output uses dynamic `giraffe-language-skill` translation before workflow or for requested display. Except enterprise/user profiles, stored textual business content is standard English; raw-message/audit/metadata copies are not exceptions. Safe file/image input remains supported.

The two designated simulated DBs are valid for functional acceptance through real application/API execution. Keep data labels, authentication, tenant/object isolation, durable writes/readback, safe storage and truthful outcomes. No simulated dataset authorizes fabricated facts or skipped checks.

## External LLM keys are optional

AIVAN ships with a mock LLM provider that requires no external API keys. If the operator configures an external provider (OpenAI, Anthropic, Google, DeepSeek, Qwen), API keys are read from the `.env` file and passed only to the configured provider. Keys are never logged or stored in the database.

## Risk screening is decision support only

AIVAN's supplier risk reports are automated decision-support tools. They are not authoritative legal, compliance, sanctions, or credit decisions. Risk output must be reviewed by a human operator before acting on it.

AIVAN explicitly states in every risk report: "Absence of negative evidence is NOT proof of safety."

## AIVAN does not make final legal, credit, sanctions, or compliance decisions

AIVAN does not make binding legal, credit, sanctions, or compliance decisions. All AIVAN outputs — supplier options, risk ratings, quotes, lead-time estimates — are drafts for human review. No action is taken without explicit operator approval.

## Reporting vulnerabilities

To report a security vulnerability, open a private issue on the [AIVAN GitHub repository](https://github.com/GiraffeTechnology/aivan) or contact the Giraffe Technology team directly. Please do not disclose vulnerabilities publicly before they have been addressed.

