"""Read operator-owned SQL configuration without copying or printing credentials."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit

DRIVERS = {
    'aivan': {'mysql+pymysql', 'postgresql+psycopg2', 'postgresql+psycopg'},
    'database': {'mysql+pymysql', 'postgresql+psycopg2', 'postgresql+psycopg'},
    'abcdyi': {'mysql+aiomysql', 'postgresql+asyncpg'},
}


def safe_error(component, operation):
    return RuntimeError(f'{component} database {operation} failed; check the authorized configuration and database access')


def sql_target(component, descriptor):
    if not isinstance(descriptor, dict) or set(descriptor) - {'url', 'schema'}:
        raise ValueError(f'Invalid {component} database descriptor')
    value = descriptor.get('url')
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f'A nonblank {component} database URL is required')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in DRIVERS[component] or not parsed.hostname or parsed.fragment
                or not parsed.path.startswith('/') or not parsed.path[1:]):
            raise ValueError()
        engine = parsed.scheme.split('+', 1)[0]
        database = unquote(parsed.path[1:])
        schema = descriptor.get('schema') or (database if engine == 'mysql' else 'public')
        if not isinstance(schema, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$-]{0,127}', schema):
            raise ValueError()
        if engine == 'mysql' and schema != database:
            raise ValueError()
        target = {'engine': engine, 'host': parsed.hostname.lower(), 'port': parsed.port or (3306 if engine == 'mysql' else 5432),
                  'database': database, 'schema': schema}
    except (TypeError, ValueError, KeyError):
        raise ValueError(f'Unsupported or invalid {component} database URL; MySQL/PostgreSQL configuration is required') from None
    # The identity excludes secrets. Changing a password does not change the store.
    fingerprint = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()
    return {'url': value, 'schema': schema, 'target_sha256': fingerprint, 'engine': engine,
            'namespace': (engine, target['host'], target['port'], database, schema)}


def configured_targets(config, root):
    mode = config.get('database_mode', 'external')
    if mode == 'isolated':
        if config.get('host_profile') != 'isolated':
            raise ValueError('SQLite is permitted only in the explicitly selected isolated test profile')
        return {
            'aivan': {'url': config.get('external', {}).get('aivan_database_url') or f'sqlite:///{root}/data/aivan.db', 'schema': 'main', 'engine': 'sqlite'},
            'abcdyi': {'url': f'sqlite+aiosqlite:///{root}/data/abcdyi.db', 'schema': 'main', 'engine': 'sqlite'},
            **({} if config.get('external', {}).get('database') else {
                'database': {'url': f'sqlite+pysqlite:///{root}/data/giraffe.db', 'schema': 'main', 'engine': 'sqlite'}}),
        }
    if mode != 'external':
        raise ValueError('Unknown database configuration mode')
    path = Path(config.get('database_config_file') or '')
    if not path.is_absolute():
        raise ValueError('Supply the authorized private database configuration file before startup')
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError('Database configuration must be a private owner-only regular file')
            contents = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError('The authorized private database configuration cannot be read') from None
    if not isinstance(contents, dict) or set(contents) != {'version', 'databases'} or type(contents['version']) is not int or contents['version'] != 1:
        raise ValueError('Unsupported private database configuration schema')
    databases = contents['databases']
    required = {'aivan', 'abcdyi'} | (set() if config.get('external', {}).get('database') else {'database'})
    if not isinstance(databases, dict) or set(databases) != required:
        raise ValueError('Provide distinct Aivan/abcdYi SQL targets and provider SQL unless an external provider HTTP API is selected')
    targets = {name: sql_target(name, value) for name, value in databases.items()}
    identities = [item['namespace'] for item in targets.values()]
    if len(set(identities)) != len(identities):
        raise ValueError('Application table inventories require distinct database/schema namespaces')
    legacy = config.get('external', {}).get('aivan_database_url')
    if legacy and legacy != targets['aivan']['url']:
        raise ValueError('Legacy Aivan database configuration conflicts with the selected private configuration')
    return targets


def sync_url(url):
    if url.startswith('mysql+aiomysql:'):
        return url.replace('mysql+aiomysql:', 'mysql+pymysql:', 1)
    if url.startswith('postgresql+asyncpg:'):
        return url.replace('postgresql+asyncpg:', 'postgresql+psycopg2:', 1)
    return url.replace('sqlite+aiosqlite:', 'sqlite:', 1)


def verify_namespace(engine, expected):
    from sqlalchemy import inspect
    if inspect(engine).default_schema_name != expected:
        raise RuntimeError('The connected database namespace differs from its authorized configuration')


def schema_issues(engine, metadata):
    from sqlalchemy import inspect, text, Text
    inspector = inspect(engine)
    actual = set(inspector.get_table_names())
    issues = []
    for table in metadata.tables.values():
        if table.name not in actual:
            issues.append('missing_table:' + table.name)
        else:
            columns = {column['name']: column for column in inspector.get_columns(table.name)}
            issues.extend('missing_column:' + table.name + '.' + name for name in table.columns.keys() if name not in columns)
            if engine.dialect.name in {'mysql', 'postgresql'}:
                for column in table.columns:
                    if column.name not in columns:
                        continue
                    expected = column.type.dialect_impl(engine.dialect)
                    actual_type = columns[column.name]['type']
                    expected_length = getattr(expected, 'length', None)
                    actual_length = getattr(actual_type, 'length', None)
                    if (actual_length is not None and
                            (isinstance(expected, Text) or expected_length is not None and actual_length < expected_length)):
                        issues.append('insufficient_string_capacity:' + table.name + '.' + column.name)
    if engine.dialect.name == 'mysql':
        identities = {(table.name, column.name) for table in metadata.tables.values() for column in table.columns
                      if column.primary_key or column.unique or column.name in {'id', 'created_by', 'updated_by'}
                      or column.name.endswith(('_id', '_key'))}
        with engine.connect() as connection:
            rows = connection.execute(text('SELECT TABLE_NAME, COLUMN_NAME, COLLATION_NAME FROM information_schema.COLUMNS '
                                           'WHERE TABLE_SCHEMA = :schema AND COLLATION_NAME IS NOT NULL'),
                                      {'schema': inspector.default_schema_name})
            for table, column, collation in rows:
                if (table, column) in identities and not (collation == 'binary' or collation.endswith('_bin')):
                    issues.append('identity_collation:' + table + '.' + column + ':' + collation)
    return sorted(issues)


def require_schema(engine, metadata):
    issues = schema_issues(engine, metadata)
    if issues:
        raise RuntimeError('Configured SQL schema is not compatible; inspect database-plan before explicit migration')


def physical_namespace(engine, target):
    from sqlalchemy import text
    with engine.connect() as connection:
        if target['engine'] == 'mysql':
            server, database = connection.execute(text('SELECT @@server_uuid, DATABASE()')).one()
            return (target['engine'], str(server), database, target['schema'])
        address, port, database = connection.execute(text('SELECT inet_server_addr()::text, inet_server_port(), current_database()')).one()
        return (target['engine'], str(address), port, database, target['schema'])


def verify_physical_namespaces(targets):
    from sqlalchemy import create_engine
    identities = []
    for target in targets.values():
        if target['engine'] == 'sqlite':
            continue
        engine = create_engine(sync_url(target['url']))
        try:
            verify_namespace(engine, target['schema'])
            identities.append(physical_namespace(engine, target))
        finally:
            engine.dispose()
    if len(set(identities)) != len(identities):
        raise RuntimeError('The connected applications share a physical database namespace')
