"""Process-local abcdYi launcher and installation-owned tenant login bridge.

The isolated source root is never installed as top-level Aivan. Credentials are
read only from the supervisor's private environment, never request bodies/files.
"""
from __future__ import annotations

import argparse
import importlib.util
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


def database_helpers():
    spec = importlib.util.spec_from_file_location('myaivan_database_config', Path(__file__).with_name('database_config.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def initialize():
    load_source()
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session
    from src.db.base import Base
    import src.db.models  # noqa: F401 - register independently packaged models.
    from src.db.models.tenant import Tenant
    from src.db.models.user import User, UserRole
    from api.auth import hash_password, validate_secret_key

    validate_secret_key(os.environ.get('SECRET_KEY'))
    url = os.environ['DATABASE_URL']
    helpers = database_helpers()
    isolated = os.environ.get('MYAIVAN_DATABASE_MODE') == 'isolated'
    if not isolated:
        helpers.sql_target('abcdyi', {'url':url, 'schema':json.loads(os.environ['MYAIVAN_DATABASE_SCHEMAS'])['abcdyi']})
    elif not url.startswith('sqlite+aiosqlite:///'):
        raise RuntimeError('The isolated test profile requires its local execution database')
    engine = create_engine(helpers.sync_url(url))
    helpers.verify_namespace(engine, json.loads(os.environ.get('MYAIVAN_DATABASE_SCHEMAS','{"abcdyi":"main"}'))['abcdyi'])
    actual = set(inspect(engine).get_table_names())
    if not actual:
        if not isolated:
            raise RuntimeError('External fulfillment schema is empty; run database-plan and explicit database-migrate')
        Base.metadata.create_all(engine)
    helpers.require_schema(engine, Base.metadata)
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



def create_buyer(tenant_name, email, full_name, password):
    """Create a distinct buyer profile; never modify an existing account or grant admin."""
    load_source()
    spec = importlib.util.spec_from_file_location('myaivan_buyer_setup', Path(__file__).with_name('buyer_setup.py'))
    inputs = importlib.util.module_from_spec(spec); spec.loader.exec_module(inputs)
    email, full_name = inputs.validate_inputs(tenant_name, email, full_name, password)
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import IntegrityError
    from src.db.base import Base
    from src.db.models.tenant import Tenant
    from src.db.models.user import User, UserRole
    from src.db.models.audit import AuditLog
    from api.auth import hash_password, validate_secret_key
    validate_secret_key(os.environ.get('SECRET_KEY'))
    mapping, _keys = tenant_configuration()
    if tenant_name not in mapping:
        raise ValueError('Select an existing installation tenant')
    identifiers = mapping[tenant_name]
    tenant_id, operator_id = uuid.UUID(identifiers['tenant_id']), uuid.UUID(identifiers['operator_id'])
    helpers = database_helpers()
    engine = create_engine(helpers.sync_url(os.environ['DATABASE_URL']))
    try:
        helpers.verify_namespace(engine, json.loads(os.environ['MYAIVAN_DATABASE_SCHEMAS'])['abcdyi'])
        helpers.require_schema(engine, Base.metadata)
        with Session(engine) as db:
            tenant = db.get(Tenant, tenant_id)
            operator = db.get(User, operator_id)
            if (tenant is None or not tenant.is_active or tenant.slug != tenant_name
                    or operator is None or not operator.is_active or operator.tenant_id != tenant_id
                    or db.scalar(select(UserRole.id).where(UserRole.user_id == operator_id,
                                                          UserRole.role_name == 'ADMIN')) is None):
                raise ValueError('The installation tenant and operator must already be active')
            if db.scalar(select(User.id).where(User.email == email)) is not None:
                raise ValueError('An account with this email already exists; no account was changed')
            buyer = User(id=uuid.uuid4(), tenant_id=tenant_id, email=email, full_name=full_name,
                         hashed_password=hash_password(password), is_active=True, is_platform_admin=False)
            db.add(buyer); db.flush()
            db.add(UserRole(user_id=buyer.id, role_name='BUYER'))
            db.add(AuditLog(tenant_id=tenant_id, user_id=operator_id, action='BUYER_ACCOUNT_CREATED',
                resource_type='user', resource_id=str(buyer.id),
                payload={'role': 'BUYER', 'provisioning_method': 'local_installer_operator',
                         'project_membership_required': True}))
            db.commit()
            return {'created': True, 'user_id': str(buyer.id), 'tenant_id': str(tenant_id),
                    'provider_tenant_id': tenant_name, 'email': email, 'roles': ['BUYER'],
                    'plaintext_password_retained': False, 'project_membership_required': True}
    except IntegrityError:
        raise ValueError('Account creation conflicted; no existing account was changed') from None
    finally:
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
    parser.add_argument('command', choices=['bootstrap', 'serve', 'verify-import', 'buyer-create'])
    parser.add_argument('root', nargs='?')
    parser.add_argument('--fd', type=int)
    parser.add_argument('--tenant')
    parser.add_argument('--email')
    parser.add_argument('--full-name')
    args = parser.parse_args()
    if args.command == 'buyer-create':
        spec = importlib.util.spec_from_file_location('myaivan_buyer_inputs', Path(__file__).with_name('buyer_setup.py'))
        inputs = importlib.util.module_from_spec(spec); spec.loader.exec_module(inputs)
        try:
            created = inputs.interactive(args.tenant, args.email, args.full_name, create=create_buyer)
        except ValueError as exc:
            print(json.dumps({'error': 'buyer_configuration_rejected', 'message': str(exc)}), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(created))
    elif args.command == 'bootstrap':
        initialize()
    elif args.command == 'verify-import':
        root = load_source()
        import aivan
        if Path(aivan.__file__).resolve().is_relative_to(root):
            raise RuntimeError('Historical abcdYi Aivan shadowed the current Aivan wheel')
        import api.main  # noqa: F401 - verify the isolated application import.
        print('Independent abcdYi API and current Aivan imports verified')
    else:
        if args.fd is None:
            raise RuntimeError('The installation supervisor must supply its reserved service socket')
        import uvicorn
        uvicorn.run(application(), fd=args.fd, access_log=False, proxy_headers=False)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error':'fulfillment_database_or_service_operation_failed','error_type':type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
