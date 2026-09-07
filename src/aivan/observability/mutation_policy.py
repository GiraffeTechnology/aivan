"""Validated, machine-readable inventory for application mutation routes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from starlette.routing import compile_path


MutationClassification = Literal["guarded", "not_applicable"]
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_POLICY_VERSION = "aivan.mutation-policy.v1"


@dataclass(frozen=True)
class MutationPolicyEntry:
    method: str
    path_template: str
    classification: MutationClassification
    reason: str
    policy_version: str = _POLICY_VERSION


def _load_entries() -> tuple[MutationPolicyEntry, ...]:
    path = Path(__file__).with_name("mutation_policy.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("policy_version") != _POLICY_VERSION:
        raise RuntimeError("AIVAN_MUTATION_POLICY_VERSION_INVALID")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise RuntimeError("AIVAN_MUTATION_POLICY_EMPTY")
    entries: list[MutationPolicyEntry] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise RuntimeError("AIVAN_MUTATION_POLICY_ENTRY_INVALID")
        method = str(raw.get("method", "")).upper()
        path_template = str(raw.get("path_template", ""))
        classification = str(raw.get("classification", ""))
        reason = str(raw.get("reason", "")).strip()
        key = (method, path_template)
        if (
            method not in _MUTATION_METHODS
            or not path_template.startswith("/")
            or classification not in {"guarded", "not_applicable"}
            or not reason
            or key in seen
        ):
            raise RuntimeError("AIVAN_MUTATION_POLICY_ENTRY_INVALID")
        seen.add(key)
        entries.append(
            MutationPolicyEntry(
                method=method,
                path_template=path_template,
                classification=cast(MutationClassification, classification),
                reason=reason,
            )
        )
    return tuple(entries)


_ENTRIES = _load_entries()
_COMPILED = tuple((entry, compile_path(entry.path_template)[0]) for entry in _ENTRIES)


def mutation_policy_entries() -> tuple[MutationPolicyEntry, ...]:
    return _ENTRIES


def mutation_classification(method: str, path: str) -> MutationClassification | None:
    normalized_method = method.upper()
    if normalized_method not in _MUTATION_METHODS:
        return None
    matches = [
        entry.classification
        for entry, pattern in _COMPILED
        if entry.method == normalized_method and pattern.fullmatch(path)
    ]
    if len(matches) > 1:
        raise RuntimeError("AIVAN_MUTATION_POLICY_AMBIGUOUS")
    return matches[0] if matches else None
