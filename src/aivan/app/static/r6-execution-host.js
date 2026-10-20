'use strict';

// The server owns association, authentication and resource authorization.
// This client only maps the delivered R6 read vocabulary to that fixed API.
window.myAivanR6Host = (() => {
  const uuid = value => typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  const caseReference = value => typeof value === 'string'
    && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$/.test(value);

  function createReadResolver(caseId, association) {
    if (!caseReference(caseId) || !association
        || association.schema_version !== 'aivan.execution-association.v1'
        || association.case_id !== caseId) throw Error('EXECUTION_ASSOCIATION_INVALID');
    if (association.status !== 'associated' || association.readback_verified !== true
        || association.execution_reads_available !== true) return null;
    const prefix = `/api/workbench/cases/${encodeURIComponent(caseId)}/execution`;
    if (!uuid(association.local_order_id) || !uuid(association.local_project_id)) {
      throw Error('EXECUTION_ASSOCIATION_INVALID');
    }
    if (association.execution_read_prefix !== prefix) throw Error('EXECUTION_READ_PATH_UNAVAILABLE');
    const order = association.local_order_id;
    const paths = new Map([
      [`/api/orders/${order}`, '/order'],
      [`/api/orders/${order}/production-monitoring`, '/production'],
      [`/api/orders/${order}/qc-records`, '/qc'],
      [`/api/execution-graph/orders/${order}`, '/events'],
    ]);
    return path => {
      if (typeof path !== 'string') throw Error('EXECUTION_READ_PATH_UNAVAILABLE');
      if (paths.has(path)) return prefix + paths.get(path);
      const match = /^\/api\/shipments\/([^/]+)$/.exec(path);
      if (match && uuid(match[1])) {
        // R6 supplies shipment IDs from returned evidence; the server checks
        // their ownership against this case/order on every read.
        return `${prefix}/shipments/${encodeURIComponent(match[1])}`;
      }
      throw Error('EXECUTION_READ_PATH_UNAVAILABLE');
    };
  }

  function bind(container, source) {
    const runtime = window.myAivanR6Execution;
    if (!container || !runtime || typeof runtime.mountExecutionHost !== 'function'
        || typeof runtime.bindExecutionHost !== 'function') {
      throw Error('EXECUTION_ASSETS_UNAVAILABLE');
    }
    return runtime.bindExecutionHost({
      container, hostSource: source, mountExecutionHost: runtime.mountExecutionHost,
      onError() {
        // No host events, error payloads, credentials or resource data in diagnostics.
        container.dataset.executionError = 'unavailable';
      },
    });
  }

  return Object.freeze({createReadResolver, bind});
})();
