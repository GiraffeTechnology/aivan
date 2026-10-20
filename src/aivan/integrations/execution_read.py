"""Case-bound reads through the existing installation operator JWT bridge."""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import urlsplit

import httpx

from aivan.api.request_context import RequestContext
from aivan.integrations.execution_association import _uuid

_DEFAULT_TRANSPORT: httpx.BaseTransport | None = None
_TOKEN = re.compile(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$')


class ExecutionReadError(RuntimeError):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def _invalid_number(value):
    raise ValueError('Non-JSON numeric value')


def _json(response):
    try:
        if len(response.content) > 8_000_000:
            raise ValueError()
        return json.loads(response.content, parse_constant=_invalid_number)
    except (ValueError, UnicodeError):
        raise ExecutionReadError(502, 'EXECUTION_RESPONSE_INVALID') from None


class ExecutionReadClient:
    """No business writes, arbitrary destination, role projection or cached facts."""

    def __init__(self, context: RequestContext, *, transport=None):
        self.context = context
        # Only the actual installer-configured Web operator may use its bridge.
        # Possession of a different admin role or API key is not this binding.
        actor = os.environ.get('MYAIVAN_EXECUTION_WEB_ACTOR_ID', '')
        if (context.authorization_basis != 'ui_session' or context.role_context != 'admin'
                or not actor or actor != 'installation-operator' or context.actor_id != actor
                or os.environ.get('AIVAN_UI_ACTOR_ID') != actor):
            raise ExecutionReadError(403, 'EXECUTION_READ_FORBIDDEN')
        try:
            self.base = os.environ['MYAIVAN_EXECUTION_BASE_URL']
            if any(ord(char) < 33 or ord(char) > 126 for char in self.base):
                raise ValueError()
            url = urlsplit(self.base)
            if (url.scheme != 'http' or url.hostname not in {'127.0.0.1', '::1'}
                    or url.username or url.password or url.query or url.fragment
                    or url.path not in {'', '/'} or url.port is None or url.port < 1024):
                raise ValueError()
            mappings = json.loads(os.environ['MYAIVAN_FULFILLMENT_TENANTS'])
            keys = json.loads(os.environ['MYAIVAN_FULFILLMENT_API_KEYS'])
            binding = mappings[context.tenant_id]
            if not isinstance(binding, dict) or set(binding) != {'tenant_id', 'operator_id'}:
                raise ValueError()
            self.tenant = _uuid(binding['tenant_id'])
            self.operator = _uuid(binding['operator_id'])
            self.key = keys[context.tenant_id]
            if (not isinstance(self.key, str) or len(self.key) < 32 or not self.key.isascii()
                    or any(ord(c) < 33 or ord(c) > 126 for c in self.key)):
                raise ValueError()
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise ExecutionReadError(503, 'EXECUTION_READ_CONFIGURATION_UNAVAILABLE') from None
        self.transport = transport if transport is not None else _DEFAULT_TRANSPORT

    def _request(self, client, method, path, headers):
        try:
            response = client.request(method, path, headers=headers)
        except httpx.HTTPError:
            raise ExecutionReadError(503, 'EXECUTION_READ_UNAVAILABLE') from None
        if response.status_code != 200:
            if method == 'POST':
                status = 503 if response.status_code in {401, 403, 429} or response.status_code >= 500 else 502
                code = 'EXECUTION_AUTHENTICATION_UNAVAILABLE'
            else:
                status = response.status_code if response.status_code in {401, 403, 404, 409, 422, 429, 503} else 503 if response.status_code >= 500 else 502
                code = 'EXECUTION_READ_REJECTED'
            # Neither private error body nor redirect/cookie headers escape.
            raise ExecutionReadError(status, code)
        return response, _json(response)

    def _token(self, client):
        _, body = self._request(client, 'POST', '/api/installation/session', {
            'X-AIVAN-Tenant-ID': self.context.tenant_id, 'X-AIVAN-API-Key': self.key,
            'X-AIVAN-Trace-ID': self.context.trace_id,
        })
        try:
            token = body['access_token']
            if (body['token_type'] != 'bearer' or body['tenant_id'] != self.tenant
                    or body['provider_tenant_id'] != self.context.tenant_id
                    or not isinstance(token, str) or not _TOKEN.fullmatch(token)):
                raise ValueError()
            payload = token.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
            if claims['sub'] != self.operator:
                raise ValueError()
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ExecutionReadError(502, 'EXECUTION_IDENTITY_MISMATCH') from None
        # Inspecting sub binds the returned credential; it is not JWT verification.
        # The execution API still verifies its signature,expiry,user and ACL.
        return token

    def read(self, association: dict, resource: str, *, shipment_id=None):
        try:
            if (association['schema_version'] != 'aivan.execution-association.v1'
                    or association['status'] != 'associated' or association['readback_verified'] is not True):
                raise ValueError()
            order_id, project_id = _uuid(association['local_order_id']), _uuid(association['local_project_id'])
            paths = {'order': f'/api/orders/{order_id}',
                     'production': f'/api/orders/{order_id}/production-monitoring',
                     'qc': f'/api/orders/{order_id}/qc-records',
                     'events': f'/api/execution-graph/orders/{order_id}'}
            if resource == 'shipment':
                shipment_id = _uuid(shipment_id)
                path = f'/api/shipments/{shipment_id}'
            else:
                path = paths[resource]
        except (KeyError, TypeError, ValueError, RuntimeError):
            raise ExecutionReadError(409, 'EXECUTION_ASSOCIATION_UNAVAILABLE') from None
        with httpx.Client(base_url=self.base, transport=self.transport, timeout=10,
                          trust_env=False, follow_redirects=False) as client:
            headers = {'Authorization': 'Bearer ' + self._token(client),
                       'X-AIVAN-Trace-ID': self.context.trace_id}
            response, order = self._request(client, 'GET', paths['order'], headers)
            if (not isinstance(order, dict) or order.get('id') != order_id
                    or order.get('project_id') != project_id):
                raise ExecutionReadError(502, 'EXECUTION_RESPONSE_IDENTITY_MISMATCH')
            if resource == 'order':
                return response
            response, body = self._request(client, 'GET', path, headers)
            if resource in {'qc', 'events'}:
                valid = isinstance(body, list) and all(isinstance(row, dict) and row.get('order_id') == order_id
                    and (resource != 'events' or row.get('tenant_id') == self.tenant) for row in body)
            elif resource == 'shipment':
                valid = isinstance(body, dict) and body.get('id') == shipment_id and body.get('order_id') == order_id
            else:
                valid = isinstance(body, dict) and isinstance(body.get('milestones'), list)
            if not valid:
                raise ExecutionReadError(502, 'EXECUTION_RESPONSE_IDENTITY_MISMATCH')
            return response
