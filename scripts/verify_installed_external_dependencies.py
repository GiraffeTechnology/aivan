#!/usr/bin/env python3
"""Exercise installed API hot-swapping with isolated synthetic SQL and credentials.

Launches the exact packaged provider, GLTG and GPM code as separate loopback
processes, using the same authoritative test database. No source patching, mock
transport, production target or external message is permitted. Restore the
original installation profile through supported CLI commands on every exit.
Run with the candidate's bundled Python using -B -I inside its service network namespace.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid
from urllib.parse import urlsplit

import httpx


def sha(value):
    return hashlib.sha256(value).hexdigest()


def private_json(path, value):
    with open(path, 'x', encoding='utf-8', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--workflow-evidence', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--synthetic-only', action='store_true')
    parser.add_argument('--allow-local-restarts', action='store_true')
    args = parser.parse_args()
    if not args.synthetic_only or not args.allow_local_restarts:
        raise ValueError('Explicit isolated synthetic fixture and restart authorization is required')
    root = args.prefix.resolve()
    release = (root / 'current').resolve()
    if release.parent != (root / 'releases').resolve():
        raise ValueError('The installed release must remain inside the installation')
    before = json.loads((root / 'config.json').read_text())
    if before.get('external') or before.get('channels', {}).get('email_enabled'):
        raise ValueError('Begin with bundled dependencies and disabled email')
    if set(before['tenants']) != {'tenant-a', 'tenant-b'}:
        raise ValueError('This test requires its two explicitly synthetic tenants')
    sql = json.loads(Path(before['database_config_file']).read_text())
    if any(urlsplit(item['url']).hostname not in {'127.0.0.1', 'localhost', '::1'}
           for item in sql['databases'].values()):
        raise ValueError('Only local synthetic SQL targets may be exercised')
    previous = json.loads(args.workflow_evidence.read_text())
    if previous.get('status') != 'passed':
        raise ValueError('A completed packaged synthetic workflow is required first')
    milestones = previous['milestones']
    case_id = milestones['chinese_intake_and_idempotent_replay']['case_id']
    po_id = milestones['human_confirmed_order_durable_readback']['purchase_order_id']
    gpm_id = milestones['supplier_reply_quote_preview_and_human_approval']['gpm_packet_id']
    order_id = milestones['production_failed_qc_rework_reinspection']['order_id']
    output = args.evidence.resolve()
    output.mkdir(mode=0o700)
    private_dir = root / 'run' / ('hot-swap-private-' + uuid.uuid4().hex)
    private_dir.mkdir(mode=0o700)
    result = {'status': 'running', 'boundary': 'real packaged loopback APIs and existing synthetic MySQL records',
              'production': False, 'external_messages_sent': 0, 'checks': [],
              'manifest_sha256': sha((release / 'manifest.json').read_bytes()),
              'runner_sha256': sha(Path(__file__).read_bytes()),
              'workflow_evidence_sha256': sha(args.workflow_evidence.read_bytes())}
    def flush():
        (output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    def check(name, passed, **details):
        result['checks'].append({'name': name, 'passed': bool(passed), **details}); flush()
        if not passed:
            raise AssertionError(name)
    def command(name, *values):
        proc = subprocess.run([str(root / 'myaivan'), *map(str, values)], capture_output=True, timeout=300)
        (output / (name + '.stdout')).write_bytes(proc.stdout)
        (output / (name + '.stderr')).write_bytes(proc.stderr)
        check(name, proc.returncode == 0, exit_code=proc.returncode)
        return json.loads(proc.stdout)
    spec = importlib.util.spec_from_file_location('installed_runtime', release / 'runtime.py')
    runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
    environment = runtime.environment(root, release, before)
    command('verify-original-release', 'verify')
    private_json(private_dir / 'original-config.json', before)
    checks = httpx.Client(trust_env=False, follow_redirects=False, timeout=30)
    def web_headers(tenant='tenant-a'):
        return {'X-AIVAN-Tenant-ID': tenant, 'X-AIVAN-API-Key': before['tenants'][tenant],
                'X-AIVAN-Actor-ID': 'installation-operator', 'X-AIVAN-Role-Context': 'admin'}
    def request(url, method, path, headers, body=None, status=(200,)):
        response = checks.request(method, url + path, headers=headers, json=body)
        check(method + ' ' + path, response.status_code in status, status_code=response.status_code)
        return response.json()
    def web_url():
        return 'http://127.0.0.1:' + str(json.loads((root / 'config.json').read_text())['ports']['web'])
    attachments_before = request(web_url(), 'GET', f'/api/workbench/cases/{case_id}/attachments', web_headers())
    confirmation_before = request(web_url(), 'GET', f'/api/workbench/cases/{case_id}/order-confirmation', web_headers())
    check('confirmed-order-precondition', confirmation_before['purchase_order_id'] == po_id)
    sockets, processes, logs = {}, [], []
    profile_changed = False
    try:
        for name in ('database', 'gltg', 'gpm'):
            listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(128)
            sockets[name] = listener
        urls = {name: 'http://127.0.0.1:' + str(listener.getsockname()[1]) for name, listener in sockets.items()}
        # Random values are ephemeral test-process identities, never real accounts.
        provider_keys = {tenant: 'synthetic-provider-' + uuid.uuid4().hex for tenant in before['tenants']}
        gpm_keys = {tenant: 'synthetic-gpm-' + uuid.uuid4().hex for tenant in before['tenants']}
        gltg_key = 'synthetic-gltg-' + uuid.uuid4().hex
        clone = {**environment, 'GIRAFFE_DB_BASE_URL': urls['database'],
                 'GIRAFFE_DB_SERVICE_AUTH_SECRET': '',
                 'GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON': json.dumps(provider_keys),
                 'GLTG_GIRAFFE_DB_BASE_URL': urls['database'], 'GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET': '',
                 'GLTG_GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON': json.dumps(provider_keys),
                 'GLTG_API_BASE_URL': urls['gltg'], 'GLTG_SERVICE_AUTH_SECRET': gltg_key,
                 'GLTG_INBOUND_SERVICE_AUTH_SECRET': gltg_key, 'GPM_API_BASE_URL': urls['gpm'],
                 'GPM_TENANT_API_KEYS': json.dumps(gpm_keys)}
        for name, listener in sockets.items():
            env = dict(clone)
            if name == 'gpm':
                env['AIVAN_TENANT_API_KEYS'] = json.dumps(gpm_keys)
            log = open(output / (name + '.log'), 'ab'); logs.append(log)
            process = subprocess.Popen([str(release / 'runtime/bin/python3'), '-B', '-I', '-m', 'uvicorn',
                runtime.SERVICES[name][0], '--fd', str(listener.fileno()), '--no-access-log', '--no-proxy-headers'],
                env=env, cwd=root, pass_fds=(listener.fileno(),), stdout=log, stderr=log)
            processes.append(process)
        for name in sockets:
            for _ in range(120):
                try:
                    if checks.get(urls[name] + runtime.SERVICES[name][1]).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.25)
            else:
                raise AssertionError('Separate packaged dependency startup failed: ' + name)
        private_json(private_dir / 'external-sql.json', {'version': 1, 'databases': {key: value for key, value in sql['databases'].items() if key != 'database'}})
        private_json(private_dir / 'service-credentials.json', {'version': 1, 'services': {
            'database': {'tenant_service_auth': provider_keys}, 'gltg': {'service_auth': gltg_key},
            'gpm': {'tenant_keys': gpm_keys}}})
        private_json(private_dir / 'external-profile.json', {'version': 1, 'external': urls,
            'database_config_file': str(private_dir / 'external-sql.json'),
            'service_credentials_file': str(private_dir / 'service-credentials.json'),
            'private_data_provider_id': before['private_data_provider_id']})
        profile_changed = True
        command('activate-independent-credentials', 'prepare', '--profile-file', private_dir / 'external-profile.json', '--restart')
        health = command('check-independent-dependencies', 'check')
        check('both-tenants-use-durable-gpm', health['ok'] and all(health['services']['gpm']['tenants'].values()))
        current = json.loads((root / 'config.json').read_text())
        check('logical-store-and-frontend-identities-preserved', current['private_data_provider_id'] == before['private_data_provider_id'] and current['tenants'] == before['tenants'] and current['fulfillment']['tenants'] == before['fulfillment']['tenants'])
        state = command('managed-service-inventory', 'status')
        check('bundled-replaced-processes-stopped', set(state['processes']['children']) == {'web', 'abcdyi', 'language'})
        db_headers = {tenant: {'X-Service-Tenant-ID': tenant, 'X-Service-Auth': key} for tenant, key in provider_keys.items()}
        purchase = request(urls['database'], 'GET', '/api/data/purchase-orders/' + po_id, db_headers['tenant-a'])
        execution_before = request(urls['database'], 'GET', f'/api/data/purchase-orders/{po_id}/execution-state', db_headers['tenant-a'])
        request(urls['database'], 'GET', '/api/data/purchase-orders/' + po_id, db_headers['tenant-b'], status=(404,))
        wrong = dict(db_headers['tenant-b'], **{'X-Service-Auth': provider_keys['tenant-a']})
        request(urls['database'], 'GET', '/api/data/purchase-orders/' + po_id, wrong, status=(401, 403))
        request(urls['database'], 'GET', '/api/data/purchase-orders/' + po_id,
                {'X-Service-Tenant-ID': 'tenant-a', 'X-Service-Auth': before['secrets']['database']}, status=(401, 403))
        confirmation = request(web_url(), 'GET', f'/api/workbench/cases/{case_id}/order-confirmation', web_headers())
        check('aivan-provider-confirmation-readback', confirmation['purchase_order_id'] == po_id)
        attachments_after = request(web_url(), 'GET', f'/api/workbench/cases/{case_id}/attachments', web_headers())
        check('aivan-attachment-provider-readback', attachments_before == attachments_after)
        abcdyi = 'http://127.0.0.1:' + str(current['ports']['abcdyi'])
        login = request(abcdyi, 'POST', '/api/installation/session', web_headers())
        restored = request(abcdyi, 'POST', '/api/orders/from-provider-confirmed',
                           {'Authorization': 'Bearer ' + login['access_token']}, {'purchase_order_id': po_id})
        check('execution-uuid-selects-correct-provider-tenant', restored['id'] == order_id and restored['status'] == 'BUYER_SIGNED_OFF')
        execution_after = request(urls['database'], 'GET', f'/api/data/purchase-orders/{po_id}/execution-state', db_headers['tenant-a'])
        check('hot-swap-keeps-execution-authority', execution_after == execution_before)
        gpm_headers = {**web_headers(), 'X-AIVAN-API-Key': gpm_keys['tenant-a']}
        packet = request(urls['gpm'], 'GET', '/api/gpm/quote-guidance/' + gpm_id, gpm_headers)
        request(urls['gpm'], 'GET', '/api/gpm/quote-guidance/' + gpm_id, web_headers(), status=(401, 403))
        simulation = request(urls['gltg'], 'POST', '/v2/lead-time/simulate',
            {'X-Service-Auth': gltg_key, 'X-Service-Tenant-ID': 'tenant-a'},
            {'request_id': 'hot-swap-' + uuid.uuid4().hex, 'tenant_id': 'tenant-a',
             'order': {'product_type': 'cotton shirt', 'quantity': 1200, 'deadline_days': 120},
             'supplier': {'supplier_id': purchase['supplier_id']}, 'evidence': {'use_giraffe_db': True}})
        check('gltg-read-and-write-with-tenant-credential', simulation['persistence']['status'] == 'persisted' and simulation['explanation_json']['evidence']['tenant_id'] == 'tenant-a')
        os.environ.update(runtime.environment(root, release, current))
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
            os.environ.pop(key, None)
        from aivan.integrations import gpm_guidance_client
        check("uses-exact-installed-gpm-client", Path(gpm_guidance_client.__file__).resolve().is_relative_to(release))
        GPMGuidanceClient = gpm_guidance_client.GPMGuidanceClient
        fields = ('case_id', 'quote_id', 'sku', 'supplier_id', 'supplier_quote', 'currency', 'quantity',
                  'buyer_unit_price', 'buyer_total', 'supplier_total', 'margin_rate', 'gltg_run_id', 'gltg_api_version')
        token = 'hot-swap-' + uuid.uuid4().hex
        guidance = GPMGuidanceClient().create_guidance(tenant_id='tenant-a', actor_id='installation-operator', actor_role='admin',
            trace_id=token, idempotency_key=token, **{key: packet[key] for key in fields})
        check('installed-aivan-gpm-client-uses-independent-credentials', guidance['human_approval_required'] is True and guidance['dispatched'] is False and guidance['approval_status'] == 'pending')
        stored = request(urls['database'], 'GET', '/api/data/gpm/packets/' + guidance['packet_id'], db_headers['tenant-a'])
        check('guidance-write-survives-private-provider-readback', stored['packet_id'] == guidance['packet_id'])
        result['status'] = 'passed'
    except Exception as exc:
        result['status'] = 'failed'; result['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        if profile_changed:
            try:
                command('stop-external-profile', 'stop')
                command('restore-original-configuration', 'configure', '--file', private_dir / 'original-config.json')
                command('restart-bundled-profile', 'start')
                command('verify-restored-profile', 'check')
                result['original_profile_restored'] = True
            except Exception as exc:
                result['status'] = 'failed'; result['original_profile_restored'] = False
                result['recovery_failure'] = type(exc).__name__
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        for listener in sockets.values():
            listener.close()
        for log in logs:
            log.close()
        checks.close(); flush()
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']), 'evidence': str(output / 'results.json')}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
