"""Explicit synthetic identity fixtures and read-only SQL verification.

Business workflow state is never created or changed here. The caller must be an
isolated installed-package acceptance run. Credentials stay in process memory.
"""
from __future__ import annotations

import json
import importlib.util
import hashlib
import os
import re
import secrets
from pathlib import Path


def sql_targets(prefix: Path) -> dict:
    from sqlalchemy.engine import make_url

    config = json.loads((prefix / "config.json").read_text())
    if config.get("database_mode") != "external":
        raise ValueError("Acceptance requires the real MySQL three-schema profile")
    values = json.loads(Path(config["database_config_file"]).read_text())["databases"]
    if set(values) != {"aivan", "abcdyi", "database"}:
        raise ValueError("All three configured SQL schemas are required")
    for target in values.values():
        url = make_url(target["url"])
        if url.get_backend_name() != "mysql" or url.host != "127.0.0.1":
            raise ValueError("Only explicitly isolated loopback MySQL is supported")
    return values


def provision_buyer(prefix: Path, release: Path, tenant: str, run_id: str) -> dict:
    """Use the shipped operator provisioning function with a synthetic secret."""
    config = json.loads((prefix / "config.json").read_text())
    sql_targets(prefix)
    manifest = json.loads((release / "manifest.json").read_text())
    bound_modules = {}
    for name in ("abcdyi_service.py", "buyer_setup.py", "runtime.py"):
        digest = hashlib.sha256((release / name).read_bytes()).hexdigest()
        if manifest["files"].get(name) != digest:
            raise ValueError("Buyer provisioning module differs from the verified candidate")
        bound_modules[name] = digest
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    runtime = load("verified_acceptance_runtime", release / "runtime.py")
    os.environ.update(runtime.environment(prefix, release, config))
    service = load("verified_acceptance_buyer_setup", release / "abcdyi_service.py")
    if not hasattr(service, "create_buyer"):
        raise ValueError("This candidate lacks supported separate buyer provisioning")
    email = f"acceptance-buyer-{run_id}@example.invalid"
    password = secrets.token_urlsafe(36)
    receipt = service.create_buyer(tenant, email, "Synthetic acceptance buyer", password)
    if receipt.get("created") is not True or receipt.get("roles") != ["BUYER"]:
        raise AssertionError("Installed buyer provisioning did not create exactly the buyer role")
    return {"id": receipt["user_id"], "email": email, "password": password,
            "provisioning_method": "installed abcdyi_service.create_buyer",
            "provisioning_modules_sha256": bound_modules,
            "provisioning_receipt": receipt, "synthetic": True}


def verify_mysql_and_no_cjk(prefix: Path) -> dict:
    """Read every textual/JSON value; emit counts and locations, never secrets."""
    from sqlalchemy import create_engine, inspect, text

    pattern = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

    def has_cjk(value):
        if isinstance(value, dict):
            return any(has_cjk(k) or has_cjk(v) for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return any(has_cjk(v) for v in value)
        if isinstance(value, str):
            if pattern.search(value):
                return True
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                return False
            return decoded != value and has_cjk(decoded)
        return False

    results = {}
    for component, target in sql_targets(prefix).items():
        engine = create_engine(target["url"].replace("+aiomysql", "+pymysql"))
        violations = []
        counts = {}
        with engine.connect() as connection:
            version, mode = connection.execute(text("SELECT VERSION(), @@sql_mode")).one()
            if "STRICT_TRANS_TABLES" not in mode:
                raise AssertionError("Strict MySQL mode is required")
            inspector = inspect(connection)
            for table in inspector.get_table_names():
                columns = [col["name"] for col in inspector.get_columns(table)
                           if any(token in str(col["type"]).lower() for token in ("char", "text", "json"))]
                quoted = engine.dialect.identifier_preparer.quote
                counts[table] = connection.execute(text(f"SELECT COUNT(*) FROM {quoted(table)}")).scalar_one()
                if columns:
                    query = f"SELECT {', '.join(quoted(col) for col in columns)} FROM {quoted(table)}"
                    for index, row in enumerate(connection.execute(text(query))):
                        violations.extend({"table": table, "column": col, "row_index": index}
                                          for col, value in zip(columns, row) if has_cjk(value))
        results[component] = {"version": version, "strict_mode": mode, "row_counts": counts,
                              "cjk_violations": violations, "read_only_scan": True}
        engine.dispose()
    return results
