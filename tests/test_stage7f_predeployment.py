from __future__ import annotations

import json

from aivan.db.models import Base
from scripts.run_stage7f_predeployment import (
    EVIDENCE_CLASS,
    REQUIRED_OBSERVATIONS,
    run_predeployment_gate,
)
from sqlalchemy import create_engine


def _repository(tmp_path):
    for name, content in (
        ("pyproject.toml", "[project]\nname='predeployment-test'\n"),
        ("uv.lock", "version = 1\n"),
        ("integrations/openclaw-aivan-plugin/package-lock.json", "{}\n"),
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    engine = create_engine(f"sqlite:///{(data / 'aivan.db').as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return tmp_path


def _environment(path, candidate, *, cors="https://myaivan.com"):
    secret = "must-not-enter-evidence"
    path.write_text(
        "\n".join(
            (
                "AIVAN_ENV=production",
                f"AIVAN_CANDIDATE_SHA={candidate}",
                "AIVAN_HOST=127.0.0.1",
                "AIVAN_PORT=8765",
                "AIVAN_DB_URL=sqlite:///./data/aivan.db",
                "AIVAN_NON_CHINA_EGRESS_POLICY=abcdyi-sin",
                f"AIVAN_CORS_ORIGINS={cors}",
                "AIVAN_REQUIRE_HUMAN_APPROVAL=true",
                "AIVAN_EXTERNAL_MODEL_API_ENABLED=false",
                "AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED=false",
                "AIVAN_ALLOW_STUB_SUPPLIERS=false",
                "OPENCLAW_MOCK_MODE=false",
                f"AIVAN_API_KEY={secret}-api",
                "AIVAN_TENANT_ID=tenant-test",
                "AIVAN_UI_ACTOR_ID=actor-test",
                f"AIVAN_UI_SESSION_SECRET={secret}-session-value-long-enough",
                "OPENCLAW_BASE_URL=http://127.0.0.1:18770",
                f"OPENCLAW_API_KEY={secret}-openclaw",
                "GIRAFFE_DB_BASE_URL=http://127.0.0.1:11080",
                f"GIRAFFE_DB_SERVICE_AUTH_SECRET={secret}-giraffe",
                "OLLAMA_MODEL=qwen3.5:9b",
                "AIVAN_LANGUAGE_SKILL_ENABLED=true",
                "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER=ctranslate2",
                "AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL=opus-mt",
                "AIVAN_LANGUAGE_SKILL_EXPECTED_BACKEND=cpu",
                "AIVAN_TRANSLATION_PROOFREAD_ENABLED=true",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return secret


def _topology(path, *, preserved=True):
    observations = {name: True for name in REQUIRED_OBSERVATIONS}
    observations["protected_ports_preserved"] = preserved
    payload = {
        "schema_version": 1,
        "profile": "ctyun-aivan-myaivan",
        "cloud": "ctyun-cn",
        "install_path": "/opt/giraffe/aivan",
        "service_name": "myaivan.service",
        "bind_host": "127.0.0.1",
        "bind_port": 8765,
        "database_profile": "sqlite:///./data/aivan.db",
        "non_china_egress_bridge": "abcdyi-sin",
        "protected_port_owners": {"443": "nginx", "8443": "stalwart"},
        "reverse_bridge": {
            "remote_host_profile": "abcdyi-sin",
            "remote_bind": "127.0.0.1",
            "remote_port": 18765,
            "health_path": "/health",
        },
        "expected_local_model": "qwen3.5:9b",
        "observations": observations,
        "observation_digests": {name: "a" * 64 for name in REQUIRED_OBSERVATIONS},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_predeployment_gate_passes_without_recording_secrets(tmp_path):
    repository = _repository(tmp_path)
    candidate = "c" * 40
    environment = tmp_path / "production.env"
    topology = tmp_path / "topology.json"
    output = tmp_path / "evidence.jsonl"
    secret = _environment(environment, candidate)
    _topology(topology)

    result = run_predeployment_gate(
        repository_root=repository,
        candidate_commit=candidate,
        environment_file=environment,
        topology_file=topology,
        output_path=output,
    )

    stored_text = output.read_text(encoding="utf-8")
    stored = json.loads(stored_text)
    assert result["status"] == "passed"
    assert stored["evidence_class"] == EVIDENCE_CLASS == "production_predeployment"
    assert stored["production_acceptance"] is False
    assert stored["candidate_commit"] == candidate
    assert stored["schema_issue_count"] == 0
    assert stored["environment_profile"]["secret_values_recorded"] is False
    assert secret not in stored_text
    assert "AIVAN_API_KEY=" not in stored_text


def test_predeployment_gate_fails_closed_for_cors_or_protected_port_gap(tmp_path):
    repository = _repository(tmp_path)
    candidate = "d" * 40
    environment = tmp_path / "production.env"
    topology = tmp_path / "topology.json"
    _environment(environment, candidate, cors="*")
    _topology(topology, preserved=False)

    result = run_predeployment_gate(
        repository_root=repository,
        candidate_commit=candidate,
        environment_file=environment,
        topology_file=topology,
        output_path=tmp_path / "evidence.jsonl",
    )

    failed = {item["code"] for item in result["checks"] if item["result"] == "failed"}
    assert result["status"] == "failed_closed"
    assert "cors_exact_origin" in failed
    assert "observation_protected_ports_preserved" in failed


def test_predeployment_gate_requires_immutable_candidate(tmp_path):
    repository = _repository(tmp_path)
    environment = tmp_path / "production.env"
    topology = tmp_path / "topology.json"
    _environment(environment, "e" * 40)
    _topology(topology)

    try:
        run_predeployment_gate(
            repository_root=repository,
            candidate_commit="branch-or-short-sha",
            environment_file=environment,
            topology_file=topology,
            output_path=tmp_path / "evidence.jsonl",
        )
    except ValueError as exc:
        assert "full 40-character" in str(exc)
    else:
        raise AssertionError("mutable candidate identity must fail closed")
