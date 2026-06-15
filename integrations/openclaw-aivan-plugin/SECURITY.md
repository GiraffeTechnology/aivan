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

## Local SQLite data boundary

All trade data — buyer requirements, supplier details, conversations, risk reports, drafts — is stored exclusively in a local SQLite file (`data/aivan.db`). This data does not leave the operator's machine unless:
- The operator explicitly approves a draft message (sent via OpenClaw)
- The operator configures an external LLM provider (optional; mock is default)

## External LLM keys are optional

AIVAN ships with a mock LLM provider that requires no external API keys. If the operator configures an external provider (OpenAI, Anthropic, Google, DeepSeek, Qwen), API keys are read from the `.env` file and passed only to the configured provider. Keys are never logged or stored in the database.

## Risk screening is decision support only

AIVAN's supplier risk reports are automated decision-support tools. They are not authoritative legal, compliance, sanctions, or credit decisions. Risk output must be reviewed by a human operator before acting on it.

AIVAN explicitly states in every risk report: "Absence of negative evidence is NOT proof of safety."

## AIVAN does not make final legal, credit, sanctions, or compliance decisions

AIVAN does not make binding legal, credit, sanctions, or compliance decisions. All AIVAN outputs — supplier options, risk ratings, quotes, lead-time estimates — are drafts for human review. No action is taken without explicit operator approval.

## Reporting vulnerabilities

To report a security vulnerability, open a private issue on the [AIVAN GitHub repository](https://github.com/GiraffeTechnology/aivan) or contact the Giraffe Technology team directly. Please do not disclose vulnerabilities publicly before they have been addressed.
