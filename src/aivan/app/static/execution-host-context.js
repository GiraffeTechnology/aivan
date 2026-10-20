'use strict';

// An injection boundary, not a router, association provider or authentication API.
window.myAivanExecutionHostContext = (() => {
  const aborted = () => new DOMException('Execution context changed.', 'AbortError');
  const nonempty = value => typeof value === 'string' && value.trim().length > 0;

  function create() {
    let generation = 0;
    let disposed = false;
    let activated = false;
    let lifetime = new AbortController();
    let event = Object.freeze({generation, reason:'signed-out', context:null});
    const listeners = new Set();

    function deliver(listener, value) {
      try { listener(value); }
      catch { /* One consumer must not prevent invalidation of the others. */ }
    }
    function publish(reason, context) {
      event = Object.freeze({generation, reason, context});
      const published = event;
      for (const listener of [...listeners]) {
        if (event !== published) break; // Reentrant invalidation supersedes this event.
        if (listeners.has(listener)) deliver(listener, published);
      }
    }
    const source = Object.freeze({
      snapshot: () => event,
      subscribe(listener) {
        if (typeof listener !== 'function') throw new TypeError('Listener required.');
        if (!disposed) listeners.add(listener);
        deliver(listener, event);
        return () => listeners.delete(listener);
      },
    });

    function invalidate(reason) {
      if (!['signed-out', 'context-changing'].includes(reason)) throw new TypeError('Invalid reason.');
      if (disposed) return generation;
      generation += 1;
      activated = false;
      lifetime.abort();
      lifetime = new AbortController();
      publish(reason, null);
      return generation;
    }

    function activate(input) {
      if (disposed || activated || input?.generation !== generation) return false;
      if (!nonempty(input.sessionKey) || !(input.orderId === null || nonempty(input.orderId))
        || (input.shipmentId !== undefined && !nonempty(input.shipmentId))) {
        throw new TypeError('Invalid execution context.');
      }
      // The authenticated host resolves/validates the association; client flags
      // cannot prove it. No resolver or order mapping means reads are unavailable.
      const resolver = input.resolveReadPath;
      const selectedGeneration = generation;
      const signal = lifetime.signal;
      const orderId = typeof resolver === 'function' ? input.orderId : null;
      const current = () => !disposed && generation === selectedGeneration && !signal.aborted;
      const request = async (path, options) => {
        if (!current()) throw aborted();
        if (options?.method !== 'GET' || !(options.signal instanceof AbortSignal)) {
          throw new TypeError('GET and AbortSignal required.');
        }
        if (options.signal.aborted) throw aborted();
        if (orderId === null || typeof resolver !== 'function') throw Error('EXECUTION_ASSOCIATION_UNAVAILABLE');
        if (typeof path !== 'string' || !path) throw Error('EXECUTION_READ_PATH_UNAVAILABLE');
        const route = resolver(path);
        if (!current()) throw aborted();
        if (typeof route !== 'string' || !route.startsWith('/') || route.startsWith('//')
          || /[\\#\u0000-\u0020\u007f]/.test(route)) throw Error('EXECUTION_READ_PATH_UNAVAILABLE');
        let decoded;
        try { decoded = decodeURIComponent(route.split('?')[0]); }
        catch { throw Error('EXECUTION_READ_PATH_UNAVAILABLE'); }
        if (decoded.startsWith('//') || /[\\%\u0000-\u0020\u007f]/.test(decoded)
          || decoded.split('/').some(segment => segment === '.' || segment === '..')) {
          throw Error('EXECUTION_READ_PATH_UNAVAILABLE');
        }
        const url = new URL(route, window.location.origin);
        if (url.origin !== window.location.origin || url.username || url.password || url.hash) {
          throw Error('EXECUTION_READ_PATH_UNAVAILABLE');
        }
        // Native composition remains attached through Response body consumption.
        // Do not detach cancellation as soon as the headers arrive.
        if (typeof AbortSignal.any !== 'function') throw Error('EXECUTION_ABORT_COMPOSITION_UNAVAILABLE');
        const combined = AbortSignal.any([signal, options.signal]);
        const response = await fetch(url.href, {
          method:'GET', credentials:'same-origin', redirect:'error', cache:'no-store', signal:combined,
        });
        if (!current() || combined.aborted) throw aborted();
        return response; // Preserve the native Response, including error status/body.
      };
      const context = Object.freeze({
        sessionKey:input.sessionKey, orderId,
        ...(orderId === null || input.shipmentId === undefined ? {} : {shipmentId:input.shipmentId}), request,
      });
      activated = true;
      publish(orderId === null ? 'association-unavailable' : 'ready', context);
      return current();
    }

    function dispose() {
      if (disposed) return;
      disposed = true;
      generation += 1;
      lifetime.abort();
      publish('disposed', null);
      listeners.clear();
    }
    return Object.freeze({source, invalidate, activate, dispose});
  }
  return Object.freeze({create});
})();
