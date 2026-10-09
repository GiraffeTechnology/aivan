"""Synthetic no-network checks for authenticated installed-service probes."""
import importlib.util
import json
from pathlib import Path

import pytest


def helper():
    spec = importlib.util.spec_from_file_location('installed_health_test', Path(__file__).parents[1] / 'installer/healthcheck.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('url', [
    'http://gpm.example.invalid/api/gpm/readiness',
    'http://[::]/api/gpm/readiness',
    'http://127.example.invalid/api/gpm/readiness',
    'https://user:password@gpm.example.invalid/api/gpm/readiness',
    'file:///tmp/not-a-service',
])
def test_authenticated_unsafe_target_fails_before_network(monkeypatch, url):
    module = helper()
    calls = []
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *a: calls.append(a))
    with pytest.raises(ValueError) as error:
        module.request_json(url, {'X-AIVAN-API-Key': 'synthetic-test-credential'})
    assert calls == []
    assert 'synthetic-test-credential' not in str(error.value)
    assert 'password' not in str(error.value)


@pytest.mark.parametrize('url', [
    'http://127.0.0.1:9000/api/gpm/readiness',
    'http://localhost:9000/api/gpm/readiness',
    'http://[::1]:9000/api/gpm/readiness',
    'https://gpm.example.invalid/api/gpm/readiness',
])
def test_secure_or_loopback_target_uses_real_probe_path(monkeypatch, url):
    module = helper()
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return json.dumps({'status': 'ok'}).encode()
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.get_header('X-aivan-api-key'), timeout))
            return Response()
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *a: Opener())
    assert module.request_json(url, {'X-AIVAN-API-Key': 'synthetic-test-credential'}) == {'status': 'ok'}
    assert calls == [(url, 'synthetic-test-credential', 5)]


def test_probe_reports_plain_http_credential_target_unhealthy(monkeypatch):
    module = helper()
    calls = []
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *a: calls.append(a))
    report = module.probe({'ports': {'gpm': 9000}, 'external': {'gpm': 'http://gpm.example.invalid'},
                           'tenants': {'tenant-a': 'synthetic-test-credential'}},
                          {'gpm': ('aivan.gpm.server:app', '/health')},
                          {'gpm': {'tenant_keys': {'tenant-a': 'synthetic-test-credential'}}})
    assert report['gpm']['ok'] is False
    assert report['gpm']['status'] == 'https_required'
    assert 'Configure HTTPS' in report['gpm']['message']
    assert calls == []
    assert 'synthetic-test-credential' not in json.dumps(report)


@pytest.mark.parametrize('target', [
    'http://gpm.example.invalid/next',
    'https://other.example.invalid/next',
    'https://gpm.example.invalid/next',
])
def test_redirect_handler_never_replays_authenticated_headers(target):
    module = helper()
    request = module.urllib.request.Request('https://gpm.example.invalid/start',
        headers={'X-AIVAN-API-Key': 'synthetic-test-credential'})
    assert module.NoRedirect().redirect_request(request, None, 302, 'Found', {}, target) is None


def test_authenticated_opener_disables_proxy_and_redirect_handlers(monkeypatch):
    module = helper()
    handlers = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return b'{}'
    class Opener:
        def open(self, *args, **kwargs): return Response()
    def capture(*selected):
        handlers.extend(selected)
        return Opener()
    monkeypatch.setattr(module.urllib.request, 'build_opener', capture)
    assert module.request_json('https://gpm.example.invalid/health', {'X-AIVAN-API-Key': 'synthetic'}) == {}
    assert any(isinstance(h, module.NoRedirect) for h in handlers)
    assert any(isinstance(h, module.urllib.request.ProxyHandler) and h.proxies == {} for h in handlers)


@pytest.mark.parametrize('headers', [None, {'X-Request-ID': 'synthetic-trace'}])
def test_uncredentialed_health_http_remains_supported(monkeypatch, headers):
    module = helper()
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return b'{"status":"ok"}'
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'http://gpm.example.invalid/health'
            return Response()
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *args: Opener())
    assert module.request_json('http://gpm.example.invalid/health', headers) == {'status': 'ok'}
