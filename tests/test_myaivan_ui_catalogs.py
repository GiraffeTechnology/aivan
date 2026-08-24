from __future__ import annotations

import ast
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aivan.api.main import app
from aivan.app.ui_catalog import (
    GENERATED_LOCALES,
    POLICY_VERSION,
    SCHEMA_VERSION,
    canonical_messages,
    catalog_etag,
    catalog_version,
    load_generated_catalog,
    ready_locales,
    source_map,
    validate_generated_catalog,
    validate_catalog_directory,
)
from aivan.integrations.outbound_translation import OutboundTranslation, TranslationUnavailable


CANDIDATE = "c" * 40


def _payload(locale: str, *, proofreader: bool = True) -> dict:
    messages = {key: f"{locale}:{value}" for key, value in canonical_messages().items()}
    item_proofreader = (
        {"role": "proofread-only", "model": "qwen3.5:9b", "status": "accepted"}
        if proofreader
        else None
    )
    provenance = {
        key: {
            "provider": "ctranslate2",
            "model": "opus-mt",
            "backend": "cpu",
            "proofreader": item_proofreader,
        }
        for key in messages
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "locale": locale,
        "source_locale": "en",
        "catalog_version": catalog_version(),
        "candidate_sha": CANDIDATE,
        "policy_version": POLICY_VERSION,
        "provider": "ctranslate2",
        "model": "opus-mt",
        "backend": "cpu",
        "proofreader": (
            {"role": "proofread-only", "model": "qwen3.5:9b", "statuses": ["accepted"]}
            if proofreader
            else None
        ),
        "messages": messages,
        "message_provenance": provenance,
    }


def _write_catalog(directory: Path, locale: str, payload: dict | None = None) -> Path:
    path = directory / f"{locale}.json"
    path.write_text(json.dumps(payload or _payload(locale), ensure_ascii=False), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    return path


@pytest.fixture
def catalog_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AIVAN_CANDIDATE_SHA", CANDIDATE)
    monkeypatch.setenv("AIVAN_UI_CATALOG_DIR", str(tmp_path))
    if os.name != "nt":
        tmp_path.chmod(0o700)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, tmp_path


def test_english_manifest_is_fixed_and_forces_revalidation(catalog_client):
    client, _ = catalog_client
    response = client.get("/api/ui/catalogs/en")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    payload = response.json()
    assert payload["candidate_sha"] == CANDIDATE
    assert payload["messages"] == canonical_messages()
    assert set(payload["source_map"].values()) == set(canonical_messages())
    cached = client.get("/api/ui/catalogs/en", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304


def test_python_and_browser_authoritative_english_manifests_are_identical():
    root = Path(__file__).resolve().parents[1]
    javascript = (root / "src/aivan/app/static/i18n.js").read_text(encoding="utf-8")
    marker = "  const en = "
    end_marker = "\n  const zht ="
    start = javascript.index(marker) + len(marker)
    end = javascript.index(end_marker, start)
    browser_manifest = ast.literal_eval(javascript[start:end].strip().removesuffix(";"))
    assert len(browser_manifest) == 128
    assert browser_manifest == {
        source: canonical_messages()[message_id]
        for source, message_id in source_map().items()
    }


@pytest.mark.parametrize("locale", GENERATED_LOCALES)
def test_generated_catalog_api_serves_only_complete_validated_files(catalog_client, locale):
    client, directory = catalog_client
    assert client.get(f"/api/ui/catalogs/{locale}").status_code == 503
    _write_catalog(directory, locale)
    response = client.get(f"/api/ui/catalogs/{locale}?candidate={CANDIDATE}")
    assert response.status_code == 200
    assert "stale-if-error" not in response.headers["cache-control"]
    assert response.json()["messages"] == _payload(locale)["messages"]


def test_catalog_api_rejects_illegal_locale_and_candidate(catalog_client):
    client, _ = catalog_client
    assert client.get("/api/ui/catalogs/ru").status_code == 404
    assert client.get(f"/api/ui/catalogs/fr?candidate={'d' * 40}").status_code == 409


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda p: p["messages"].pop(next(iter(p["messages"]))), "message set"),
        (lambda p: p.update(candidate_sha="d" * 40), "candidate"),
        (lambda p: p.update(provider="mock"), "provider"),
        (lambda p: p.update(model="qwen3.5:9b"), "generator identity"),
        (lambda p: p.update(backend="qwen3.5:9b"), "generator identity"),
        (lambda p: p.update(backend="ollama"), "generator identity"),
        (lambda p: p.update(backend="mock-backend"), "generator identity"),
        (
            lambda p: next(iter(p["message_provenance"].values())).update(backend="qwen"),
            "message generator identity",
        ),
        (lambda p: p["messages"].update({next(iter(p["messages"])): ""}), "invalid text"),
        (
            lambda p: next(iter(p["message_provenance"].values()))["proofreader"].update(status="unknown"),
            "status",
        ),
        (
            lambda p: next(iter(p["message_provenance"].values())).update(proofreader=None),
            "inconsistent",
        ),
    ],
)
def test_catalog_validation_fails_closed(mutation, message):
    payload = _payload("fr")
    mutation(payload)
    with pytest.raises(ValueError, match=message):
        validate_generated_catalog(payload, locale="fr", candidate_sha=CANDIDATE)


def test_etag_covers_translated_messages():
    first = _payload("fr")
    second = json.loads(json.dumps(first))
    second["messages"][next(iter(second["messages"]))] += " changed"
    assert catalog_etag(first) != catalog_etag(second)


def test_readiness_requires_all_five_candidate_bound_catalogs(monkeypatch, tmp_path):
    monkeypatch.setenv("AIVAN_CANDIDATE_SHA", CANDIDATE)
    monkeypatch.setenv("AIVAN_UI_CATALOG_DIR", str(tmp_path))
    if os.name != "nt":
        tmp_path.chmod(0o700)
    assert ready_locales(CANDIDATE) == []
    for locale in GENERATED_LOCALES:
        _write_catalog(tmp_path, locale)
    assert ready_locales(CANDIDATE) == list(GENERATED_LOCALES)


def test_catalog_reader_rejects_symlink_and_unsafe_permissions(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permission and O_NOFOLLOW contract")
    tmp_path.chmod(0o700)
    target = _write_catalog(tmp_path, "fr")
    target.chmod(0o666)
    with pytest.raises(ValueError, match="permissions"):
        load_generated_catalog("fr", candidate_sha=CANDIDATE, directory=tmp_path)
    target.unlink()
    external = tmp_path.parent / "outside.json"
    external.write_text(json.dumps(_payload("fr")), encoding="utf-8")
    (tmp_path / "fr.json").symlink_to(external)
    with pytest.raises(ValueError, match="invalid|unavailable"):
        load_generated_catalog("fr", candidate_sha=CANDIDATE, directory=tmp_path)


def test_catalog_directory_rejects_symlink_parent_and_public_mode(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX path ownership contract")
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    catalogs = actual / "catalogs"
    catalogs.mkdir(mode=0o700)
    link = tmp_path / "parent-link"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink component"):
        validate_catalog_directory(link / "catalogs")
    catalogs.chmod(0o755)
    with pytest.raises(ValueError, match="permissions"):
        validate_catalog_directory(catalogs)


def test_catalog_directory_owner_must_match_service(monkeypatch, tmp_path):
    import aivan.app.ui_catalog as ui_catalog

    if os.name == "nt":
        pytest.skip("POSIX directory-owner contract")
    tmp_path.chmod(0o700)
    actual_uid = getattr(tmp_path.stat(), "st_uid", 0)
    monkeypatch.setattr(ui_catalog, "_effective_uid", lambda: actual_uid + 1)
    with pytest.raises(ValueError, match="owner"):
        validate_catalog_directory(tmp_path)
    assert ui_catalog._owned_by_service(SimpleNamespace(st_uid=actual_uid + 1)) is True
    assert ui_catalog._owned_by_service(SimpleNamespace(st_uid=actual_uid)) is False


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o666])
def test_catalog_file_rejects_non_private_mode(monkeypatch, tmp_path, mode):
    if os.name == "nt":
        pytest.skip("POSIX file-mode contract")
    monkeypatch.setenv("AIVAN_CANDIDATE_SHA", CANDIDATE)
    tmp_path.chmod(0o700)
    path = _write_catalog(tmp_path, "fr")
    path.chmod(mode)
    with pytest.raises(ValueError, match="permissions"):
        load_generated_catalog("fr", candidate_sha=CANDIDATE, directory=tmp_path)


def test_catalog_file_owner_must_match_service(monkeypatch, tmp_path):
    import aivan.app.ui_catalog as ui_catalog

    if os.name == "nt":
        pytest.skip("POSIX file-owner contract")
    tmp_path.chmod(0o700)
    _write_catalog(tmp_path, "fr")
    real_fstat = ui_catalog.os.fstat

    def wrong_file_owner(descriptor):
        result = real_fstat(descriptor)
        if not stat.S_ISREG(result.st_mode):
            return result
        values = list(result)
        values[4] = result.st_uid + 1
        return os.stat_result(values)

    monkeypatch.setattr(ui_catalog.os, "fstat", wrong_file_owner)
    with pytest.raises(ValueError, match="permissions"):
        load_generated_catalog("fr", candidate_sha=CANDIDATE, directory=tmp_path)


def test_generator_uses_every_authoritative_english_message(monkeypatch):
    import scripts.generate_myaivan_ui_catalogs as generator

    captured: list[tuple[str, str, str, str]] = []

    def translate(source, locale, *, target_channel, message_type, business_refs, client):
        captured.append((source, locale, target_channel, message_type, business_refs))
        return OutboundTranslation(
            text=f"FR:{source}", target_language=locale, provider="ctranslate2",
            model="opus-mt", backend="cpu", proofread=True,
            proofreader_model="qwen3.5:9b", proofreader_status="accepted",
        )

    monkeypatch.setattr(generator, "translate_authoritative_english", translate)
    payload = generator.generate_locale("fr", CANDIDATE, workers=3)
    assert {item[0] for item in captured} == set(canonical_messages().values())
    assert all(item[1:4] == ("fr", "myaivan_ui", "ui_label") for item in captured)
    assert {item[4]["message_id"] for item in captured} == set(canonical_messages())
    assert {item[4]["catalog_version"] for item in captured} == {catalog_version()}
    assert payload["provider"] == "ctranslate2"


def test_generator_failure_never_writes_partial_catalog(monkeypatch, tmp_path):
    import scripts.generate_myaivan_ui_catalogs as generator

    monkeypatch.setattr(
        generator,
        "translate_authoritative_english",
        lambda *args, **kwargs: (_ for _ in ()).throw(TranslationUnavailable("timeout")),
    )
    with pytest.raises(TranslationUnavailable):
        with generator.generation_lock(tmp_path, "de"):
            payload = generator.generate_locale("de", CANDIDATE)
            generator.write_atomic(tmp_path, "de", payload)
    assert not (tmp_path / "de.json").exists()


def test_atomic_writer_round_trips_through_secure_loader(tmp_path):
    import scripts.generate_myaivan_ui_catalogs as generator

    if os.name != "nt":
        tmp_path.chmod(0o700)
    target = generator.write_atomic(tmp_path, "ja", _payload("ja"))
    assert target == tmp_path / "ja.json"
    assert load_generated_catalog("ja", candidate_sha=CANDIDATE, directory=tmp_path) == _payload(
        "ja"
    )
