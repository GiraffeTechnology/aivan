"""Initialize only a fresh installer-owned schema; validate existing databases."""
import json
import importlib.util
import os
from pathlib import Path
import sys
import subprocess

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from aivan.db.models import Base as AivanBase
from aivan.db.schema_validation import require_current_schema
from giraffe_db.db.base import Base as ProviderBase
from giraffe_db.db.models.core import Tenant


def initialize(root: Path):
    config = json.loads((root / "config.json").read_text())
    spec = importlib.util.spec_from_file_location("myaivan_database_config", Path(__file__).with_name("database_config.py"))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    targets = helpers.configured_targets(config, root)
    helpers.verify_physical_namespaces(targets)
    isolated = config.get("database_mode") == "isolated"
    app_url = os.environ["AIVAN_DB_URL"]
    app = create_engine(app_url)
    helpers.verify_namespace(app, targets["aivan"]["schema"])
    if not inspect(app).get_table_names() and isolated and not config["external"].get("aivan_database_url"):
        AivanBase.metadata.create_all(app)
    require_current_schema(app)
    helpers.require_schema(app, AivanBase.metadata)
    app.dispose()
    if "abcdyi" in config["ports"]:
        subprocess.run([sys.executable, "-B", "-I", str(Path(__file__).with_name("abcdyi_service.py")), "bootstrap", str(root)], check=True)
    if "database" in config["external"]:
        return
    provider = create_engine(os.environ["GIRAFFE_DB_DATABASE_URL"])
    helpers.verify_namespace(provider, targets["database"]["schema"])
    actual = set(inspect(provider).get_table_names())
    if not actual:
        if not isolated:
            raise RuntimeError("External provider schema is empty; run database-plan and explicit database-migrate")
        assets = Path(__file__).resolve().parent / "provider-assets/giraffe-db"
        migration_config = Config(str(assets / "alembic.ini"))
        migration_config.set_main_option("script_location", str(assets / "alembic"))
        migration_config.set_main_option("prepend_sys_path", "")
        command.upgrade(migration_config, "head")
    helpers.require_schema(provider, ProviderBase.metadata)
    with Session(provider) as session:
        for tenant in config["tenants"]:
            if session.get(Tenant, tenant) is None:
                session.add(Tenant(id=tenant, name=tenant, tenant_id=tenant, source_type="installer", created_by="installation-operator"))
        session.commit()
    provider.dispose()


if __name__ == "__main__":
    try:
        initialize(Path(sys.argv[1]))
    except Exception as exc:
        print(json.dumps({"error":"database_bootstrap_or_validation_failed","error_type":type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
