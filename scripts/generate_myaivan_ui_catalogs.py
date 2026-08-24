"""Generate fixed myAIVAN UI catalogs through giraffe-language-skill.

The script is an application build/deployment tool.  It never edits server
configuration and writes each complete locale atomically only after every
message passes the translator/proofreader boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from aivan.app.ui_catalog import (
    GENERATED_LOCALES,
    MAX_CATALOG_LENGTH,
    POLICY_VERSION,
    SCHEMA_VERSION,
    canonical_messages,
    catalog_version,
    validate_catalog_directory,
    validate_generated_catalog,
)
from aivan.integrations.language_skill_client import LanguageSkillClient, LanguageSkillResult
from aivan.integrations.outbound_translation import translate_authoritative_english


_SHA = re.compile(r"^[0-9a-f]{40}$")


class CatalogLanguageSkillClient(LanguageSkillClient):
    """Share one immutable model inventory across bounded catalog workers."""

    def __init__(self) -> None:
        super().__init__()
        self._catalog_models: LanguageSkillResult | None = None
        self._catalog_models_lock = threading.Lock()

    def models(self) -> LanguageSkillResult:
        with self._catalog_models_lock:
            if self._catalog_models is None:
                self._catalog_models = super().models()
            return self._catalog_models


def generate_locale(locale: str, candidate_sha: str, workers: int = 4) -> dict:
    if locale not in GENERATED_LOCALES:
        raise ValueError("unsupported generated locale")
    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("candidate SHA must be a full lowercase commit SHA")
    canonical = canonical_messages()
    client = CatalogLanguageSkillClient()
    translated: dict[str, str] = {}
    message_provenance: dict[str, dict] = {}
    identities: set[tuple[str, str, str]] = set()
    proofreader_models: set[str] = set()
    proofreader_statuses: set[str] = set()

    def translate(item: tuple[str, str]):
        message_id, english = item
        result = translate_authoritative_english(
            english,
            locale,
            target_channel="myaivan_ui",
            message_type="ui_label",
            business_refs={"catalog_version": catalog_version(), "message_id": message_id},
            client=client,
        )
        return message_id, result

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        futures = {executor.submit(translate, item): item[0] for item in canonical.items()}
        for future in as_completed(futures):
            message_id, result = future.result()
            translated[message_id] = result.text
            identities.add((result.provider, result.model, result.backend))
            proofreader = None
            if result.proofreader_model:
                proofreader_models.add(result.proofreader_model)
                proofreader_statuses.add(result.proofreader_status or "unavailable")
                proofreader = {
                    "role": "proofread-only",
                    "model": result.proofreader_model,
                    "status": result.proofreader_status or "unavailable",
                }
            message_provenance[message_id] = {
                "provider": result.provider,
                "model": result.model,
                "backend": result.backend,
                "proofreader": proofreader,
            }

    if set(translated) != set(canonical) or len(identities) != 1:
        raise RuntimeError("translator returned a partial or inconsistent catalog")
    if sum(len(value) for value in translated.values()) > MAX_CATALOG_LENGTH:
        raise RuntimeError("translated catalog exceeds the size limit")
    provider, model, backend = next(iter(identities))
    proofreader = None
    if proofreader_models:
        if proofreader_models != {"qwen3.5:9b"}:
            raise RuntimeError("unexpected proofreader model")
        proofreader = {
            "role": "proofread-only",
            "model": "qwen3.5:9b",
            "statuses": sorted(proofreader_statuses),
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "locale": locale,
        "source_locale": "en",
        "catalog_version": catalog_version(),
        "candidate_sha": candidate_sha,
        "policy_version": POLICY_VERSION,
        "provider": provider,
        "model": model,
        "backend": backend,
        "proofreader": proofreader,
        "messages": {message_id: translated[message_id] for message_id in sorted(translated)},
        "message_provenance": {
            message_id: message_provenance[message_id] for message_id in sorted(message_provenance)
        },
    }
    return validate_generated_catalog(payload, locale=locale, candidate_sha=candidate_sha)


def write_atomic(directory: Path, locale: str, payload: dict) -> Path:
    directory = validate_catalog_directory(directory, create=True)
    target = directory / f"{locale}.json"
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{locale}.", suffix=".tmp", dir=directory)
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        if os.name != "nt":
            target.chmod(0o600)
    finally:
        if temp.exists():
            temp.unlink()
    return target


@contextmanager
def generation_lock(directory: Path, locale: str):
    directory = validate_catalog_directory(directory, create=True)
    lock = directory / f".{locale}.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--locale", choices=[*GENERATED_LOCALES, "all"], default="all")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not args.output_dir.is_absolute():
        parser.error("--output-dir must be absolute")
    locales = GENERATED_LOCALES if args.locale == "all" else (args.locale,)
    for locale in locales:
        with generation_lock(args.output_dir, locale):
            payload = generate_locale(locale, args.candidate_sha, args.workers)
            path = write_atomic(args.output_dir, locale, payload)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(
            json.dumps(
                {
                    "locale": locale,
                    "catalog_version": payload["catalog_version"],
                    "message_count": len(payload["messages"]),
                    "output": str(path),
                    "sha256": digest,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
