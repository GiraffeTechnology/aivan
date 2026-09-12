"""Constant-time secret comparison that is safe for request-derived input."""

from __future__ import annotations

import hmac

__all__ = ["secure_compare_str"]


def secure_compare_str(supplied: str, expected: str) -> bool:
    """Compare two secrets in constant time without raising on non-ASCII input.

    ``hmac.compare_digest`` rejects a ``str`` holding any code point above
    U+007F with ``TypeError``. ASGI decodes request headers as latin-1, so a
    single header byte in the 0x80-0xFF range arrives here as exactly such a
    ``str``. Passing it straight to ``compare_digest`` turns an authentication
    rejection into an unhandled 500 for a caller who has not authenticated.

    Encoding both operands first keeps the comparison constant time over the
    resulting byte strings and keeps the rejection at 401/403.
    ``surrogateescape`` is required rather than strict encoding: a
    body-derived value can carry lone surrogates, which strict mode would turn
    into ``UnicodeEncodeError`` -- the same failure in a different costume.
    """
    return hmac.compare_digest(
        supplied.encode("utf-8", "surrogateescape"),
        expected.encode("utf-8", "surrogateescape"),
    )
