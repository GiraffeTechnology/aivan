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

## Local-first data boundary

All trade data — buyer requirements, supplier details, conversations, risk reports, drafts, event logs — is stored in a local SQLite database (`data/aivan.db`). Data does not leave the operator's machine unless:
- The operator approves a draft message (sent via OpenClaw)
- The operator configures an external LLM provider (optional; mock is default)

## External LLM keys are optional

The default LLM provider is `mock`, which requires no external API keys and makes no network calls. If an external provider is configured, keys are read from `.env` and passed only to the configured provider's API. Keys are never logged or stored in the database.

## Risk screening is decision support only

AIVAN's supplier risk reports are automated decision-support outputs. They are not authoritative legal, compliance, sanctions, or credit decisions. Every risk report includes the disclaimer:

> "Absence of negative evidence is NOT proof of safety. This report is for human review only."

## AIVAN does not make legal, credit, sanctions, or compliance decisions

AIVAN does not make binding legal, credit, sanctions, or compliance decisions. All outputs — supplier options, risk ratings, quotes, lead-time estimates — are drafts and recommendations for human review. No action is taken without explicit operator approval.

## Reporting vulnerabilities

To report a security vulnerability, open a private issue on the [AIVAN GitHub repository](https://github.com/GiraffeTechnology/aivan) or contact the Giraffe Technology team directly. Please do not disclose vulnerabilities publicly before they have been addressed.
