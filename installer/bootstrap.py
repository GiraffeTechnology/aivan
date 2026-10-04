"""Initialize only a fresh installer-owned schema; validate existing databases."""
import json
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
    app_url = os.environ["AIVAN_DB_URL"]
    app = create_engine(app_url)
    if not inspect(app).get_table_names() and not config["external"].get("aivan_database_url"):
        AivanBase.metadata.create_all(app)
    require_current_schema(app)
    app.dispose()
    if "abcdyi" in config["ports"]:
        subprocess.run([sys.executable, "-B", "-I", str(Path(__file__).with_name("abcdyi_service.py")), "bootstrap", str(root)], check=True)
    if "database" in config["external"]:
        return
    provider = create_engine(os.environ["GIRAFFE_DB_DATABASE_URL"])
    actual = set(inspect(provider).get_table_names())
    if not actual:
        assets = Path(__file__).resolve().parent / "provider-assets/giraffe-db"
        migration_config = Config(str(assets / "alembic.ini"))
        migration_config.set_main_option("script_location", str(assets / "alembic"))
        migration_config.set_main_option("prepend_sys_path", "")
        command.upgrade(migration_config, "head")
    else:
        schema = inspect(provider)
        for table in ProviderBase.metadata.tables.values():
            if table.name not in actual or set(table.columns.keys()) - {column["name"] for column in schema.get_columns(table.name)}:
                raise RuntimeError("Existing provider schema requires an approved migration; it was not modified")
    with Session(provider) as session:
        for tenant in config["tenants"]:
            if session.get(Tenant, tenant) is None:
                session.add(Tenant(id=tenant, name=tenant, tenant_id=tenant, source_type="installer", created_by="installation-operator"))
        session.commit()
    provider.dispose()


if __name__ == "__main__":
    initialize(Path(sys.argv[1]))
