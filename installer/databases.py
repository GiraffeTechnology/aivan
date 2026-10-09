"""Read-only database plans and explicit, verified package migration execution."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from datetime import datetime, timezone


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
CONFIG = load_module('myaivan_database_config', HERE / 'database_config.py')
RUNTIME = load_module('myaivan_verified_runtime', HERE / 'runtime.py')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def metadata(component):
    if component == 'aivan':
        from aivan.db.models import Base
    elif component == 'database':
        from giraffe_db.db.base import Base
        import giraffe_db.db.models  # noqa: F401 - register model metadata.
    else:
        source = HERE / 'services/abcdyi'
        sys.path.insert(0, str(source))
        from src.db.base import Base
        import src.db.models  # noqa: F401 - register model metadata.
    return Base.metadata


def migration_config(component):
    from alembic.config import Config
    assets = HERE / ('services/abcdyi' if component == 'abcdyi' else 'provider-assets/giraffe-db')
    config = Config(str(assets / 'alembic.ini'))
    config.set_main_option('script_location', str(assets / 'alembic'))
    config.set_main_option('prepend_sys_path', '')
    return config


def inspect_target(component, target):
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    engine = create_engine(CONFIG.sync_url(target['url']))
    try:
        CONFIG.verify_namespace(engine, target['schema'])
        inspector = inspect(engine)
        names = sorted(inspector.get_table_names())
        shape = {name: [{'name': col['name'], 'type': str(col['type']), 'nullable': col['nullable']}
                        for col in inspector.get_columns(name)] for name in names}
        issues = CONFIG.schema_issues(engine, metadata(component))
        physical = CONFIG.physical_namespace(engine, target)
        with engine.connect() as connection:
            revisions = list(MigrationContext.configure(connection).get_current_heads()) if component != 'aivan' else []
        heads = ScriptDirectory.from_config(migration_config(component)).get_heads() if component != 'aivan' else ['2026.08.10-stage7b']
        return {'engine': target['engine'], 'target_sha256': target['target_sha256'],
                'namespace_sha256': digest(physical), 'schema_sha256': digest(shape), 'empty': not names,
                'schema_current': not issues, 'schema_issues': issues,
                'current_revisions': revisions, 'target_revisions': heads,
                'unversioned_existing_schema': bool(names) and not revisions if component != 'aivan' else False}
    finally:
        engine.dispose()


def plan(root, components=None):
    manifest = RUNTIME.verify_payload(HERE)
    config = RUNTIME.read_json(root / 'config.json')
    RUNTIME.validate_config(config)
    if config.get('database_mode') != 'external':
        raise ValueError('External MySQL/PostgreSQL configuration is required for this migration workflow')
    targets = CONFIG.configured_targets(config, root)
    selected = list(components or targets)
    if not selected or set(selected) - set(targets) or len(set(selected)) != len(selected):
        raise ValueError('Select configured SQL components; an external provider HTTP API is not migrated')
    # Selection limits writes, not the namespace boundary of configured applications.
    try:
        CONFIG.verify_physical_namespaces(targets)
    except Exception:
        raise ValueError('Configured SQL targets failed physical namespace isolation verification') from None
    snapshots = {}
    for name in selected:
        try:
            snapshots[name] = inspect_target(name, targets[name])
        except Exception:
            raise CONFIG.safe_error(name, 'inspection') from None
    if len({v['namespace_sha256'] for v in snapshots.values()}) != len(snapshots):
        raise ValueError('The connected components share a physical database namespace')
    result = {'format': 1, 'release': manifest['release'], 'manifest_sha256': hashlib.sha256((HERE / 'manifest.json').read_bytes()).hexdigest(),
              'components': snapshots, 'private_provider_http': 'database' in config.get('external', {}),
              'candidate_revisions': {name: value['revision'] for name, value in manifest['components'].items()}}
    result['plan_sha256'] = digest(result)
    return result


def apply_component(component, target, snapshot, manifest, tenant, authorization, backup, bootstrap_empty):
    if snapshot['empty'] and not bootstrap_empty:
        raise ValueError('Empty SQL targets require explicit --bootstrap-empty')
    if component == 'aivan':
        if snapshot['schema_current']:
            return {'changed': False, 'schema_current': True}
        # Scripts remain independently source-pinned assets, not a host checkout.
        sys.path.insert(0, str(HERE / 'provider-assets/aivan'))
        from scripts.run_aivan_migrations import _apply_verified_candidate
        return _apply_verified_candidate(target['url'], tenant_id=tenant,
            candidate_sha=manifest['components']['aivan']['revision'], authorization_reference=authorization,
            backup_reference=backup, bootstrap_empty=bootstrap_empty)
    if snapshot['unversioned_existing_schema']:
        raise ValueError('Existing unversioned schema requires an explicitly reviewed baseline; it was not stamped')
    if set(snapshot['current_revisions']) == set(snapshot['target_revisions']) and snapshot['schema_current']:
        return {'changed': False, 'schema_current': True}
    from alembic import command
    from sqlalchemy import create_engine, inspect
    engine = create_engine(CONFIG.sync_url(target['url']))
    try:
        if snapshot['empty'] and component == 'abcdyi':
            metadata(component).create_all(engine)
            command.stamp(migration_config(component), 'head')
            return {'changed': True, 'operation': 'explicit_empty_current_metadata_baseline',
                    'table_count': len(metadata(component).tables), 'stamped_revisions': snapshot['target_revisions']}
        command.upgrade(migration_config(component), 'head')
        before_tables = set(inspect(engine).get_table_names())
        metadata(component).create_all(engine)
        added = sorted(set(inspect(engine).get_table_names()) - before_tables)
        return {'changed': True, 'operation': 'pinned_upgrade_and_declared_additive_tables', 'created_tables': added}
    finally:
        engine.dispose()


def migrate(root, expected, *, components=None, tenant, authorization, backup, bootstrap_empty=False):
    if not authorization.strip() or not backup.strip() or not tenant.strip():
        raise ValueError('Explicit authorization, recovery reference and legacy-data tenant are required')
    actual = plan(root, components or list(expected.get('components', {})))
    if actual != expected:
        raise ValueError('Database target, package or schema changed after preview; create a new plan')
    config = RUNTIME.read_json(root / 'config.json')
    if tenant not in config['tenants']:
        raise ValueError('The verified legacy-data tenant must be configured in this installation')
    targets = CONFIG.configured_targets(config, root)
    manifest = RUNTIME.verify_payload(HERE)
    if any(issue.startswith('identity_collation:') for snapshot in actual['components'].values() for issue in snapshot['schema_issues']):
        raise ValueError('Existing identity collations require a separately reviewed migration; no changes were applied')
    receipt = {'operation': 'database_migration', 'started_at': datetime.now(timezone.utc).isoformat(),
               'plan_sha256': expected['plan_sha256'], 'release': manifest['release'],
               'authorization_sha256': hashlib.sha256(authorization.encode()).hexdigest(),
               'backup_reference_sha256': hashlib.sha256(backup.encode()).hexdigest(),
               'components': {}, 'ok': False, 'atomic_across_databases': False}
    location = root / 'migrations' / (receipt['started_at'].replace(':', '-') + '.json')
    for name, snapshot in actual['components'].items():
        try:
            applied = apply_component(name, targets[name], snapshot, manifest, tenant, authorization, backup, bootstrap_empty)
            after = inspect_target(name, targets[name])
            if not after['schema_current']:
                raise RuntimeError('Schema did not converge to the verified package')
            receipt['components'][name] = {'status': 'verified', 'result': applied, 'after': after}
        except Exception as exc:
            receipt['components'][name] = {'status': 'failed', 'error_type': type(exc).__name__}
            RUNTIME.write_json(location, receipt)
            return receipt
        RUNTIME.write_json(location, receipt)
    receipt['ok'] = True
    RUNTIME.write_json(location, receipt)
    return receipt


def validate_plan_path(root, path):
    config = RUNTIME.read_json(root / 'config.json')
    resolved = path.resolve()
    protected = {(root / 'config.json').resolve()}
    if config.get('database_config_file'):
        protected.add(Path(config['database_config_file']).resolve())
    if resolved in protected or resolved.is_relative_to(HERE.resolve()):
        raise ValueError('The plan must not replace private configuration or immutable release files')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'migrate'])
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--component', action='append', choices=['aivan', 'abcdyi', 'database'])
    parser.add_argument('--plan-file', type=Path, required=True)
    parser.add_argument('--tenant-id', default='')
    parser.add_argument('--authorization-reference', default='')
    parser.add_argument('--backup-reference', default='')
    parser.add_argument('--bootstrap-empty', action='store_true')
    args = parser.parse_args()
    validate_plan_path(args.prefix, args.plan_file)
    if args.command == 'plan':
        result = plan(args.prefix, args.component)
        RUNTIME.write_json(args.plan_file, result)
        print(json.dumps({'ok': True, 'mode': 'read_only_plan', 'plan_file': str(args.plan_file), 'plan': result}))
        return 0
    expected = RUNTIME.read_json(args.plan_file)
    result = migrate(args.prefix, expected, components=args.component, tenant=args.tenant_id,
        authorization=args.authorization_reference, backup=args.backup_reference, bootstrap_empty=args.bootstrap_empty)
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': 'database_plan_or_migration_failed', 'error_type': type(exc).__name__}))
        raise SystemExit(1) from None
