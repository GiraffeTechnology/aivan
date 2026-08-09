from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping


def log_exception_safely(
    logger: logging.Logger,
    message: str,
    *,
    exc: BaseException,
    context: Mapping[str, str] | None = None,
    level: int = logging.ERROR,
) -> str:
    """Log an exception without its message, traceback, or attached payload.

    Exception strings from HTTP/database clients can contain response bodies,
    credentials, message content, or other tenant data.  Production logs only
    need a correlation identifier, the exception type, and explicitly supplied
    low-cardinality context.  The caller can use the returned ``error_id`` to
    correlate a user-visible failure with internal metrics.
    """

    error_id = uuid.uuid4().hex
    safe_context = dict(context or {})
    context_template = " ".join(f"{key}=%s" for key in safe_context)
    template = f"{message} error_id=%s exception_type=%s"
    if context_template:
        template = f"{template} {context_template}"
    logger.log(
        level,
        template,
        error_id,
        type(exc).__name__,
        *safe_context.values(),
    )
    return error_id
