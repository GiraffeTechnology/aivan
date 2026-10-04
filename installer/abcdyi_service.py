"""Process-local abcdYi launcher and installation-owned tenant login bridge.

The isolated source root is never installed as top-level Aivan. Credentials are
read only from the supervisor's private environment, never request bodies/files.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import uuid


def source_root():
    source = Path(__file__).resolve().parent / 'services/abcdyi'
    if source.is_symlink() or not (source / 'api/main.py').is_file():
        raise RuntimeError('Verified abcdYi service source is unavailable')
    return source


def load_source():
    root = source_root()
    # Do not add root/src: doing so would shadow the current Aivan wheel with
    # abcdYi's preserved historical src/aivan implementation.
    sys.path.insert(0, str(root))
    return root


def tenant_configuration():
    mapping = json.loads(os.environ['MYAIVAN_FULFILLMENT_TENANTS'])
    keys = json.loads(os.environ['MYAIVAN_FULFILLMENT_API_KEYS'])
    if not isinstance(mapping, dict) or not isinstance(keys, dict) or set(mapping) != set(keys):
        raise RuntimeError('Invalid installation tenant configuration')
    for tenant, item in mapping.items():
        if not isinstance(item, dict) or set(item) != {'tenant_id', 'operator_id'}:
            raise RuntimeError('Invalid installation tenant mapping')
        uuid.UUID(item['tenant_id']); uuid.UUID(item['operator_id'])
        if (not isinstance(keys[tenant], str) or len(keys[tenant]) < 32 or not keys[tenant].isascii()
                or any(ord(char) < 33 or ord(char) == 127 for char in keys[tenant])):
            raise RuntimeError('Invalid installation tenant credential')
    return mapping, keys


def initialize():
    load_source()
    from sqlalchemy import create_engine, inspect, select
    from sqlalchemy.orm import Session
    from src.db.base import Base
    import src.db.models  # Register the independently packaged business models.
    from src.db.models.tenant import Tenant
    from src.db.models.user import User, UserRole
    from api.auth import hash_password, validate_secret_key

    validate_secret_key(os.environ.get('SECRET_KEY'))
    url = os.environ['DATABASE_URL']
    if not url.startswith('sqlite+aiosqlite:///'):
        raise RuntimeError('Installer only initializes its own local SQLite execution view')
    engine = create_engine(url.replace('sqlite+aiosqlite:', 'sqlite:', 1))
    actual = set(inspect(engine).get_table_names())
    if not actual:
        Base.metadata.create_all(engine)
    else:
        inspector = inspect(engine)
        for table in Base.metadata.tables.values():
            if table.name not in actual or set(table.columns.keys()) - {column['name'] for column in inspector.get_columns(table.name)}:
                raise RuntimeError('Existing fulfillment schema needs a compatible release migration; it was not modified')
    mapping, _keys = tenant_configuration()
    with Session(engine) as db:
        for name, identities in mapping.items():
            tenant_id, operator_id = uuid.UUID(identities['tenant_id']), uuid.UUID(identities['operator_id'])
            tenant = db.get(Tenant, tenant_id)
            if tenant is None:
                db.add(Tenant(id=tenant_id, name=name, slug=name))
                db.flush()
            elif tenant.slug != name or not tenant.is_active:
                raise RuntimeError('Fulfillment tenant identity conflicts with installation configuration')
            operator = db.get(User, operator_id)
            if operator is None:
                # The supported login uses the existing tenant API credential.
                # No additional plaintext password is retained or distributed.
                operator = User(id=operator_id, tenant_id=tenant_id,
                    email=f'operator+{operator_id.hex}@myaivan.invalid', full_name='Installation operator',
                    hashed_password=hash_password(secrets.token_urlsafe(32)), is_platform_admin=False)
                db.add(operator)
                db.flush()
                db.add(UserRole(user_id=operator_id, role_name='ADMIN'))
            elif operator.tenant_id != tenant_id or not operator.is_active:
                raise RuntimeError('Fulfillment operator identity conflicts with installation configuration')
        db.commit()
    engine.dispose()


def application():
    load_source()
    from fastapi import Depends, Header, HTTPException
    from api.main import app
    from api.deps import get_db
    from api.auth import create_access_token
    from src.db.models.tenant import Tenant
    from src.db.models.user import User

    @app.post('/api/installation/session', tags=['installation'])
    async def installation_session(
        tenant: str = Header('', alias='X-AIVAN-Tenant-ID'),
        credential: str = Header('', alias='X-AIVAN-API-Key'),
        db=Depends(get_db),
    ):
        mapping, keys = tenant_configuration()
        expected = keys.get(tenant)
        if (expected is None or not credential.isascii()
                or not secrets.compare_digest(credential.encode('ascii'), expected.encode('ascii'))):
            raise HTTPException(401, detail='Invalid installation tenant credential')
        identities = mapping[tenant]
        user = await db.get(User, uuid.UUID(identities['operator_id']))
        tenant_row = await db.get(Tenant, uuid.UUID(identities['tenant_id']))
        if (user is None or not user.is_active or tenant_row is None or not tenant_row.is_active
                or user.tenant_id != tenant_row.id):
            raise HTTPException(401, detail='Installation tenant is unavailable')
        # This short-lived JWT enters the normal API authorization path. The
        # bridge never bypasses its project/tenant/human-role checks.
        return {'access_token': create_access_token(str(user.id)), 'token_type': 'bearer',
                'tenant_id': str(tenant_row.id), 'provider_tenant_id': tenant,
                'confirmed_order_handoff': '/api/orders/from-provider-confirmed'}
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['bootstrap', 'serve', 'verify-import'])
    parser.add_argument('root', nargs='?')
    parser.add_argument('--fd', type=int)
    args = parser.parse_args()
    if args.command == 'bootstrap':
        initialize()
    elif args.command == 'verify-import':
        root = load_source()
        import aivan
        if Path(aivan.__file__).resolve().is_relative_to(root):
            raise RuntimeError('Historical abcdYi Aivan shadowed the current Aivan wheel')
        import api.main
        print('Independent abcdYi API and current Aivan imports verified')
    else:
        if args.fd is None:
            raise RuntimeError('The installation supervisor must supply its reserved service socket')
        import uvicorn
        uvicorn.run(application(), fd=args.fd, access_log=False, proxy_headers=False)


if __name__ == '__main__':
    main()
