import re

_SECRET_PATTERNS = [
    (re.compile(r'(api[_-]?key\s*[:=]\s*)(\S+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(password\s*[:=]\s*)(\S+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(token\s*[:=]\s*)(\S+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(secret\s*[:=]\s*)(\S+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(cookie\s*[:=]\s*)(\S+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(Authorization:\s*)(\S+)', re.IGNORECASE), r'\1[REDACTED]'),
]

def redact_secrets(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text

def safe_log_dict(d: dict) -> dict:
    sensitive_keys = {'api_key', 'password', 'token', 'secret', 'cookie', 'session', 'credential', 'auth'}
    result = {}
    for k, v in d.items():
        if any(s in k.lower() for s in sensitive_keys):
            result[k] = '[REDACTED]'
        else:
            result[k] = v
    return result
