#!/usr/bin/env python3
"""Package a bounded execution-read/host delta; never install or modify a host."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import build
import build_ui_outcome_successor as engine
from build_derived import inventory, update_record, write_json

BASE_SHA256 = 'c08be0645a38dabec08520a3717035889be04b8ea2be3f1f36fe9a456b2b9e62'
BASE_REVISION = '22bdf78f393dc8e1a16483280cdf6bfeb019c236'
BASE_TREE = 'ed8d2431f014e144ca24074b785f8c7b320e6a1b'
SOURCE_REVISION = '66dbe65cb410a7082909c84069ee7c124cd5fa11'
SOURCE_TREE = '3182fff78d771f8119cab96b123f599485c6c194'
ASSET_REVISION = 'da881d30ded1d89df987c0e7d9e3cccb1902c3fc'
ASSET_NAMES = ('r6-workspace-dbdc4b643d7add02.js', 'r6-workspace-f988a2df90fe83aa.css',
               'r6-execution-LICENSES.txt', 'r6-execution-NOTICES.txt')
SITE = engine.SITE


def source_targets():
    paths = ('src/aivan/api/execution_association_routes.py', 'src/aivan/api/execution_read_routes.py',
             'src/aivan/integrations/execution_read.py', 'src/aivan/app/static/app.js',
             'src/aivan/app/templates/index.html', 'src/aivan/app/static/r6-execution-host.js',
             'src/aivan/app/static/r6-execution-assets.json',
             *('src/aivan/app/static/' + name for name in ASSET_NAMES))
    return {'installer/runtime.py': 'runtime.py', **{name: str(SITE / name[4:]) for name in paths}}


def assert_candidate_identity(revision, tree):
    if revision != SOURCE_REVISION or tree != SOURCE_TREE:
        raise ValueError('This release builder requires its exact selected source revision and tree')


def validate_changes(changes):
    runtime = set(source_targets())
    other = {'docs/SECURITY_SCANNING.md', 'tools/security/reviewed-findings.json',
             'tests/test_execution_read_boundary.py', 'tests/myaivan-handoff-wiring.test.mjs',
             'tests/myaivan-r6-host-integration.test.mjs', 'tests/myaivan-welcome-runtime.test.mjs',
             'tests/r6-host-vm-support.mjs'}
    if (not runtime.issubset(changes) or set(changes) - runtime - other
            or any(status not in {'A', 'M'} for status in changes.values())):
        raise ValueError('Source changes exceed the fixed execution-wiring release scope')


def extract_base(installer, destination):
    names = ('BASE_SHA256', 'BASE_REVISION', 'BASE_TREE')
    old = {name: getattr(engine, name) for name in names}
    try:
        for name in names:
            setattr(engine, name, globals()[name])
        return engine.extract_base(installer, destination)
    finally:
        for name, value in old.items():
            setattr(engine, name, value)


def verify_assets(source):
    root = 'src/aivan/app/static/'
    value = json.loads(build.safe_source_file(source, root + 'r6-execution-assets.json').read_text())
    if (value.get('upstream_repository') != 'GiraffeTechnology/abcdYi'
            or value.get('upstream_commit') != ASSET_REVISION
            or not isinstance(value.get('assets'), dict) or set(value['assets']) != set(ASSET_NAMES)):
        raise ValueError('Unexpected static-asset source or inventory')
    for name, entry in value['assets'].items():
        path = build.safe_source_file(source, root + name)
        if (not isinstance(entry, dict) or entry.get('bytes') != path.stat().st_size
                or entry.get('sha256') != build.digest(path)):
            raise ValueError('Static asset or retained license/notice checksum mismatch')
    return value


def verify_selection(source, baseline, revision, tree):
    assert_candidate_identity(revision, tree)
    evidence = build.source_evidence(source, revision, tree)
    if evidence['modified']:
        raise ValueError('Selected source must be clean')
    raw = build.subprocess.check_output(['git', '-C', str(source), 'diff', '--name-status', BASE_REVISION, revision])
    changes = {}
    for line in raw.decode().splitlines():
        fields = line.split('\t')
        if len(fields) != 2:
            raise ValueError('Unsupported source delta')
        changes[fields[1]] = fields[0]
    validate_changes(changes)
    if build.digest(build.safe_source_file(source, 'installer/requirements.lock')) != baseline['requirements_lock_sha256']:
        raise ValueError('Frozen runtime dependency lock changed')
    selected = []
    for name, target in source_targets().items():
        candidate = build.safe_source_file(source, name)
        result = build.subprocess.run(['git', '-C', str(source), 'show', BASE_REVISION + ':' + name],
                                      capture_output=True, check=False)
        original = hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 else None
        if baseline['files'].get(target) != original:
            raise ValueError('Installed baseline differs from its exact source member')
        selected.append({'source_path': name, 'target': target, 'base_sha256': original,
                         'candidate_sha256': build.digest(candidate)})
    return evidence, selected, verify_assets(source)


def apply_files(source, payload, selected):
    mapping = source_targets()
    if len(selected) != len(mapping) or {entry['source_path'] for entry in selected} != set(mapping):
        raise ValueError('Unexpected selected file set')
    contents = {}
    for entry in selected:
        name, target = entry['source_path'], entry['target']
        if mapping.get(name) != target:
            raise ValueError('Unselected payload target')
        data = build.safe_source_file(source, name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['candidate_sha256']:
            raise ValueError('Candidate file changed after selection')
        installed = payload / target
        if entry['base_sha256'] is None:
            if installed.exists() or installed.is_symlink():
                raise ValueError('New target already exists')
        elif build.digest(build.safe_source_file(payload, target)) != entry['base_sha256']:
            raise ValueError('Installed baseline changed after selection')
        # Base extraction forbids links; also guard parents of newly added paths.
        if any(parent.is_symlink() for parent in installed.parents if parent != payload.parent):
            raise ValueError('Payload parent links are not permitted')
        contents[target] = data
    for target, data in contents.items():
        installed = payload / target
        installed.parent.mkdir(parents=True, exist_ok=True)
        installed.write_bytes(data)


def update_selected_record(payload, distribution):
    """Register newly overlaid members before the retained integrity refresh."""
    site = payload / SITE
    record = distribution / 'RECORD'
    with record.open(newline='') as stream:
        rows = {row[0]: row for row in csv.reader(stream)}
    for target in source_targets().values():
        path = payload / target
        if path.is_relative_to(site):
            name = str(path.relative_to(site))
            rows.setdefault(name, [name, '', ''])
    with record.open('w', newline='') as stream:
        csv.writer(stream, lineterminator='\n').writerows(rows[name] for name in sorted(rows))
    update_record(site, distribution)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('base-installer', 'source', 'output'):
        parser.add_argument('--' + flag, type=Path, required=True)
    for flag in ('revision', 'tree', 'release'):
        parser.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    assert_candidate_identity(args.revision, args.tree)
    source, output = args.source.resolve(), args.output.resolve()
    if output.is_relative_to(source) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.release):
        raise ValueError('Invalid output directory or release name')
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f'myaivan-{args.release}-linux-x86_64.run'
    companions = [output / f'{args.release}-{name}.json' for name in ('manifest', 'derived-build')]
    if any(path.exists() or path.is_symlink() for path in (destination, destination.with_suffix('.tar.gz'),
            destination.with_suffix('.run.sha256'), *companions)):
        raise ValueError('Refusing to overwrite a retained artifact')
    with tempfile.TemporaryDirectory(prefix='myaivan-execution-wiring-', dir=output) as tmp:
        payload = Path(tmp) / 'payload'
        payload.mkdir()
        baseline = extract_base(args.base_installer, payload)
        if args.release == baseline['release']:
            raise ValueError('Select a new release name')
        evidence, selected, assets = verify_selection(source, baseline, args.revision, args.tree)
        apply_files(source, payload, selected)
        provenance = {'build_kind': 'offline-execution-wiring-successor', 'release': args.release,
            'base_installer_sha256': BASE_SHA256, 'selected_application_source': evidence,
            'base_derived_build': json.loads((payload / 'derived-build.json').read_text()),
            'runtime_delta': selected, 'builder_sha256': build.digest(Path(__file__)),
            'static_assets': assets, 'native_dependencies': 'Unchanged base Python/native bytes; no install or rebuild',
            'acceptance': 'Packaging only; target/MySQL/public UI/live provider/restart NOT_RUN'}
        metadata = list((payload / SITE).glob('aivan-*.dist-info'))
        if len(metadata) != 1 or metadata[0].is_symlink() or not metadata[0].is_dir():
            raise ValueError('Expected one Aivan distribution')
        write_json(metadata[0] / 'DERIVED-BUILD.json', provenance)
        update_selected_record(payload, metadata[0])
        write_json(payload / 'derived-build.json', provenance)
        manifest = copy.deepcopy(baseline)
        component = manifest['components']['aivan']
        component['base_source_evidence'] = copy.deepcopy(baseline['components']['aivan'])
        component.update(selected_source_candidate=evidence, derived_runtime_delta=selected, modified=True,
                         embedded_static_asset_provenance=assets)
        for field in ('included_source_files', 'verified_build_input_files'):
            for entry in selected:
                component[field][entry['source_path']] = entry['candidate_sha256']
        actual = inventory(payload)
        actual.pop('manifest.json')
        changed = {name for name in baseline['files'].keys() | actual.keys() if baseline['files'].get(name) != actual.get(name)}
        expected = set(source_targets().values()) | {'derived-build.json',
            str((metadata[0] / 'DERIVED-BUILD.json').relative_to(payload)), str((metadata[0] / 'RECORD').relative_to(payload))}
        if changed != expected:
            raise ValueError('Payload changed outside selected source and exact provenance')
        manifest.update(release=args.release, build_kind=provenance['build_kind'], deployment_candidate=evidence,
                        base_installer_sha256=BASE_SHA256, files=actual)
        write_json(payload / 'manifest.json', manifest)
        if build.source_evidence(source, args.revision, args.tree) != evidence:
            raise ValueError('Selected source changed during packaging')
        build.write_installer(payload, destination)
        for name in ('manifest', 'derived-build'):
            shutil.copy2(payload / f'{name}.json', output / f'{args.release}-{name}.json')
        print(json.dumps({'installer': str(destination), 'sha256': build.digest(destination),
            'bytes': destination.stat().st_size, 'candidate': evidence, 'runtime_delta': selected,
            'changed_payload_files': sorted(changed), 'deployment': 'NOT_RUN'}, indent=2))


if __name__ == '__main__':
    main()
