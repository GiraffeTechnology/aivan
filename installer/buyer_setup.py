"""Local interactive provisioning inputs for a separate native buyer identity."""
from __future__ import annotations

import getpass
import re
import sys


def validate_inputs(tenant, email, full_name, password):
    if not isinstance(tenant, str) or not tenant:
        raise ValueError('Select an existing installation tenant')
    if (not isinstance(email, str) or not email.isascii() or len(email) > 254
            or email.count('@') != 1):
        raise ValueError('A valid ASCII buyer login email is required')
    local, domain = email.split('@')
    if (not 1 <= len(local) <= 64 or local.startswith('.') or local.endswith('.') or '..' in local
            or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            or len(domain.split('.')) < 2
            or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                       for label in domain.split('.'))):
        raise ValueError('A valid buyer login email is required')
    normalized = local + '@' + domain.lower()
    if (not isinstance(full_name, str) or not full_name.strip() or len(full_name) > 255
            or any(ord(char) < 32 or ord(char) == 127 for char in full_name)):
        raise ValueError('A nonblank buyer profile name is required')
    if (not isinstance(password, str) or len(password) < 12 or len(password.encode('utf-8')) > 72
            or any(ord(char) < 32 or ord(char) == 127 for char in password)):
        raise ValueError('Choose at least 12 characters and at most 72 UTF-8 bytes without control characters')
    return normalized, full_name.strip()


def interactive(tenant, email, full_name, *, create, secret_value=None):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError('Buyer credentials must be entered directly in a private interactive terminal')
    ask = secret_value or getpass.getpass
    password = ask('New buyer password (hidden): ')
    confirmed = ask('Confirm new buyer password (hidden): ')
    if password != confirmed:
        raise ValueError('Passwords do not match; no account was created')
    validate_inputs(tenant, email, full_name, password)
    try:
        return create(tenant, email, full_name, password)
    finally:
        password = confirmed = None
