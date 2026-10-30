"""Stable attachment ownership survives invalidation of commercial graph results."""


def attachment_provider_case(project):
    payload = project.requirement_json or {}
    for key in ("giraffe_db_graph", "attachment_case_reference"):
        reference = payload.get(key)
        value = reference.get("procurement_case_id") if isinstance(reference, dict) else None
        if isinstance(value, str) and value:
            return value
    return None
