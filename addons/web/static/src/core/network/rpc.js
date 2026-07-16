// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc - JSON-RPC client built on fetch+AbortController, with error classification and request bus events */

import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { buildKey } from "@web/core/network/rpc_dedup";
import { rpcLog } from "@web/core/utils/asset_log";
import { isObject, omit } from "@web/core/utils/collections/objects";

/** @import { RPCCache } from "@web/core/network/rpc_cache" */

/**
 * Server-side payload of a JSON-RPC error response (the ``error`` slot
 * of a JSON-RPC envelope). Fields follow the JSON-RPC 2.0 spec; the
 * ``data`` member is server-defined and intentionally permissive.
 *
 * @typedef {{
 *  code: number;
 *  message: string;
 *  data?: RPCErrorData;
 *  type?: string;
 * }} JsonRpcError
 */

/**
 * Structured payload Odoo embeds in ``JsonRpcError.data``. Stable in practice —
 * downstream consumers (``error_handlers``, ``error_dialogs``,
 * ``form_controller``, ``file_upload_service``, ``domain_field``) read this
 * fixed surface, though server code may append addon-specific keys.
 *
 * @typedef {{
 *  name?: string;
 *  message?: string;
 *  arguments?: unknown[];
 *  context?: Record<string, unknown>;
 *  debug?: string;
 *  [extra: string]: unknown;
 * }} RPCErrorData
 */

/**
 * Whitelisted settings accepted by ``rpc()`` and forwarded through the
 * cache → retry → dedup composition layers. Any other key throws at
 * ``validateRPCSettings`` time so a typo surfaces immediately.
 *
 * @typedef {{
 *  cache?: boolean | { type?: "ram" | "disk"; update?: "once" | "always"; immutable?: boolean; callback?: Function };
 *  silent?: boolean;
 *  headers?: HeadersInit;
 *  timeout?: number;
 *  retry?: number | Partial<RetryConfig>;
 *  dedup?: boolean;
 * }} RpcSettings
 */

/**
 * Detail payload of the ``RpcEvent.REQUEST`` / ``RpcEvent.RESPONSE``
 * events fired on ``rpcBus``. Discriminated by the presence of
 * ``result`` (success) vs ``error`` (failure) vs neither (request).
 *
 * @typedef {{
 *  data: { id: number; jsonrpc: "2.0"; method: "call"; params: Record<string, any> };
 *  url?: string;
 *  settings?: RpcSettings;
 *  result?: any;
 *  error?: NetworkError;
 * }} RpcEventDetail
 */

/**
 * Promise returned by ``rpc()`` / ``_rpcOnce()`` / ``_rpcWithRetry()``.
 * Carries an ``abort(rejectError)`` method so callers can cancel the
 * underlying fetch. ``rejectError=true`` (default) rejects the outer
 * promise with ``ConnectionAbortedError``; ``rejectError=false`` leaves
 * it pending so the caller can silently swallow navigations.
 *
 * @template T
 * @typedef {Promise<T> & { abort: (rejectError?: boolean) => void }} RpcPromise
 */

// ── Cross-bundle singleton state ─────────────────────────────────────────
//
// ``rpcBus``, the in-flight dedup map, and the ``rpcCache`` slot are anchored
// on ``globalThis`` (like ``registry.js``'s ``__odooRegistry__`` and
// ``templates.js``'s ``__odooTemplates__``) because esbuild inlines this
// module into every bundle; per-copy state would fragment the bus, dedup map,
// and cache slot across bundles. ``??=`` keeps the FIRST bundle's instance
// authoritative.
const _RPC_STATE_KEY = "__odoo_rpc_state__";
/** @type {{ rpcBus: EventBus, inflightDedup: Map<string, Promise<any>>, rpcCache: RPCCache | null | undefined, busListenersAttached: boolean, rpcId: number }} */
const _rpcState = /** @type {any} */ (
    globalThis[_RPC_STATE_KEY] ??= {
        rpcBus: new EventBus(),
        inflightDedup: new Map(),
        rpcCache: undefined,
        busListenersAttached: false,
        // Monotonic ``data.id`` source shared across bundles via the singleton —
        // a module-level ``let`` would restart at 0 per bundle, colliding ids
        // between bundles for observers that key by ``data.id`` (loading_indicator,
        // slow_rpc_service).
        rpcId: 0,
    }
);

export const rpcBus = _rpcState.rpcBus;

const RPC_SETTINGS = new Set([
    "cache",
    "silent",
    "headers",
    "timeout",
    "retry",
    "dedup",
]);
/**
 * @param {{[key: string]: any}} settings
 */
function validateRPCSettings(settings) {
    const invalidKeys = Object.keys(settings).filter((key) => !RPC_SETTINGS.has(key));
    if (invalidKeys.length) {
        const invalid = invalidKeys.map((k) => `"${k}"`).join(", ");
        const valid = [...RPC_SETTINGS].map((k) => `"${k}"`).join(", ");
        throw new Error(
            `Invalid RPC setting(s): ${invalid}. Valid settings are: ${valid}`,
        );
    }
}

// Errors

/** Base class for all network communication failures. Catch this to handle any RPC or connection error. */
export class NetworkError extends Error {}

export class RPCError extends NetworkError {
    constructor(/** @type {any[]} */ ...args) {
        super(...args);
        /** @type {string} */
        this.name = "RPC_ERROR";
        /** @type {string | null} */
        this.type = "server";
        /** @type {number | null} */
        this.code = null;
        /** @type {RPCErrorData | null} */
        this.data = null;
        /** @type {string | null} */
        this.exceptionName = null;
        /** @type {string | null} */
        this.subType = null;
        /**
         * Model that raised the error, attached by ``_rpcOnce`` after
         * ``makeErrorFromResponse`` constructs the instance. Consumed by
         * ``error_handlers`` / ``multi_company_recovery_service`` to
         * disambiguate which model's context triggered the failure.
         *
         * @type {string | undefined}
         */
        this.model = undefined;
    }
}

export class ConnectionLostError extends NetworkError {
    /**
     * @param {string} [url]
     * @param  {...any} args
     */
    constructor(url, ...args) {
        const message = url
            ? `Connection to "${url}" couldn't be established or was interrupted`
            : "Connection couldn't be established or was interrupted";
        super(message, ...args);
        this.name = "ConnectionLostError";
        /** @type {string | undefined} */
        this.url = url;
    }
}

/**
 * Raised when the server returned a non-JSON response (typically a
 * werkzeug-rendered HTML error page from ``PoolError``, ``OperationalError``,
 * or other unhandled controller exception). Kept distinct from
 * ``ConnectionLostError`` so retry logic can apply a longer backoff floor,
 * but extends it for backward compatibility so existing
 * ``e instanceof ConnectionLostError`` catches still match.
 */
export class ServerOverloadError extends ConnectionLostError {
    /**
     * @param {string} url
     * @param {number} status HTTP status code of the non-JSON response.
     * @param {...any} args
     */
    constructor(url, status, ...args) {
        super(url, ...args);
        this.name = "ServerOverloadError";
        /** @type {number} */
        this.status = status;
        this.message = url
            ? `Server returned a non-JSON response (HTTP ${status}) at "${url}"`
            : `Server returned a non-JSON response (HTTP ${status})`;
    }
}

/**
 * Raised when the server returned a response that cannot be a JSON-RPC
 * envelope (non-JSON content type, or an unparseable body) with a NON-5xx
 * status: a session-expired POST redirected to the HTML login page (fetch
 * follows redirects), a 404 HTML page, a captive portal, an empty 200...
 * Deterministic — retrying cannot change the outcome — so ``isRetryable``
 * explicitly excludes it. Extends ``ConnectionLostError`` so existing
 * ``instanceof ConnectionLostError`` handling (connection-lost UX) still
 * matches, mirroring ``ServerOverloadError``.
 */
export class InvalidResponseError extends ConnectionLostError {
    /**
     * @param {string} url
     * @param {number} status HTTP status code of the invalid response.
     * @param {...any} args
     */
    constructor(url, status, ...args) {
        super(url, ...args);
        this.name = "InvalidResponseError";
        /** @type {number} */
        this.status = status;
        this.message = url
            ? `Server returned an invalid (non JSON-RPC) response (HTTP ${status}) at "${url}"`
            : `Server returned an invalid (non JSON-RPC) response (HTTP ${status})`;
    }
}

export class ConnectionAbortedError extends NetworkError {
    name = "ConnectionAbortedError";
}

/**
 * Raised when the request body exceeds the maximum size accepted by the
 * server (or a reverse proxy in front of it, e.g. nginx's
 * ``client_max_body_size``), which replies with an HTTP 413 response.
 */
export class RequestEntityTooLargeError extends NetworkError {
    constructor() {
        super(
            "The request you sent exceeded the maximum size limit configured on the server",
        );
        this.name = "RequestEntityTooLargeError";
    }
}

export class ConnectionTimeoutError extends NetworkError {
    /**
     * @param {string} url
     * @param {number} timeoutMs
     * @param {...any} args
     */
    constructor(url, timeoutMs, ...args) {
        super(`Request to "${url}" timed out after ${timeoutMs}ms`, ...args);
        this.name = "ConnectionTimeoutError";
        /** @type {string} */
        this.url = url;
        /** @type {number} */
        this.timeoutMs = timeoutMs;
    }
}

/**
 * @param {JsonRpcError} response
 * @returns {RPCError}
 */
export function makeErrorFromResponse(response) {
    // Odoo returns error like this, in a error field instead of properly
    // using http error codes...
    const { code, data: errorData, message, type: subType } = response;
    const error = new RPCError();
    error.exceptionName = errorData?.name ?? null;
    error.subType = subType ?? null;
    error.data = errorData ?? null;
    error.message = message;
    error.code = code;
    return error;
}

// Cache RPC method

/**
 * @param {RPCCache} cache
 */
rpc.setCache = function (cache) {
    _rpcState.rpcCache = cache;
};

// The module-level bus listeners below are attached exactly once for the
// whole document: the bus is a cross-bundle singleton, so a second bundle
// evaluating this module must not register duplicate handlers (double
// cache invalidation, double rpc logging).
if (!_rpcState.busListenersAttached) {
    _rpcState.busListenersAttached = true;

    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, (event) => {
        /** @type {{ tables?: string[]; model?: string } | string | string[] | undefined} */
        const detail = /** @type {CustomEvent<any>} */ (event).detail;
        if (isObject(detail)) {
            // ``isObject`` rejects Map/Set/Date/Array (stricter than
            // typeof === "object") but isn't a type predicate to TS, hence the
            // re-cast. ``tables`` is cast non-optional per the emit-site contract
            // ("if model is set, tables is set" — see ``RESULT_SET_TABLES`` in
            // ``services/result_set_cache_invalidator_service.js``);
            // ``invalidateByModel`` would throw on ``undefined`` regardless.
            const objDetail = /** @type {{ tables?: string[]; model?: string }} */ (
                detail
            );
            if (objDetail.model) {
                _rpcState.rpcCache?.invalidateByModel(
                    /** @type {string[]} */ (objDetail.tables),
                    objDetail.model,
                );
            } else {
                // Object detail WITHOUT a model: invalidate the named tables.
                // Passing the object itself to invalidate() (the old
                // fallthrough) fed a non-iterable into bumpDiskGeneration and
                // crashed with a TypeError, silently skipping the invalidation.
                _rpcState.rpcCache?.invalidate(objDetail.tables ?? null);
            }
            return;
        }
        // ``detail`` is a single table name (most emit sites), a ``string[]``
        // (rare, batch clearing), or ``undefined`` (full-cache nuke from
        // ``webclient.js`` after service-worker registration) — ``invalidate``
        // accepts all three.
        _rpcState.rpcCache?.invalidate(
            /** @type {string | string[] | null} */ (detail ?? null),
        );
    });

    // Observability — passive listeners mirroring RPCs into rpcLog, enabled via
    // ``localStorage.setItem("debug.rpc", "1")`` (or ``?debug=rpc``); the body
    // short-circuits on ``rpcLog.enabled()`` when disabled (one event dispatch/RPC).

    rpcBus.addEventListener(RpcEvent.REQUEST, (event) => {
        if (!rpcLog.enabled()) {
            return;
        }
        const detail = /** @type {CustomEvent<RpcEventDetail>} */ (event).detail;
        const params = detail.data?.params || {};
        rpcLog("request", detail.url, params.model || "", params.method || "");
    });

    rpcBus.addEventListener(RpcEvent.RESPONSE, (event) => {
        if (!rpcLog.enabled()) {
            return;
        }
        const detail = /** @type {CustomEvent<RpcEventDetail>} */ (event).detail;
        const params = detail.data?.params || {};
        const target = `${params.model || ""}.${params.method || detail.url}`;
        if (detail.error) {
            rpcLog(
                "error",
                target,
                detail.error.name || "error",
                detail.error.message || "",
            );
        } else {
            rpcLog("ok", target);
        }
    });
}

// Retry helpers

/**
 * @typedef {{ retries: number; baseMs: number; maxMs: number }} RetryConfig
 */

/**
 * Normalize the user-supplied ``retry`` setting to a full {@link RetryConfig}.
 * Accepts a number (as ``retries``) or a partial config; defaults suit
 * transient infra failures (proxy hiccup, pool exhaustion, worker restart):
 * three retries, ramping 200ms → 2s.
 *
 * @param {number | Partial<RetryConfig>} retry
 * @returns {RetryConfig}
 */
function normalizeRetry(retry) {
    const cfg = typeof retry === "number" ? { retries: retry } : retry;
    return {
        retries: cfg.retries ?? 3,
        baseMs: cfg.baseMs ?? 200,
        maxMs: cfg.maxMs ?? 2000,
    };
}

/**
 * Minimum delay between retries against an overloaded backend
 * (``ServerOverloadError``) — gives the worker pool / DB connections time to
 * drain before the next attempt instead of piling on.
 */
const SERVER_OVERLOAD_BACKOFF_FLOOR_MS = 1000;

/**
 * Compute the delay before the Nth retry attempt.  Exponential
 * backoff with full jitter so concurrent failing clients don't
 * thunder-herd the same recovering server.
 *
 * @param {number} attempt 1-indexed retry number (first retry = 1).
 * @param {RetryConfig} config
 * @param {unknown} [lastError] Error that triggered this retry.  When
 *   it is a ``ServerOverloadError``, a 1000ms floor is applied so the
 *   backend has time to recover.
 * @returns {number} milliseconds to wait before the next attempt.
 */
function backoffDelay(attempt, config, lastError) {
    let exp = config.baseMs * 2 ** (attempt - 1);
    if (lastError instanceof ServerOverloadError) {
        // Raise the floor; the caller's ``maxMs`` still clamps the upper
        // bound so a heavily tuned-down ``retry({ maxMs: 100 })`` config
        // remains honoured.
        exp = Math.max(exp, SERVER_OVERLOAD_BACKOFF_FLOOR_MS);
    }
    const jitter = Math.random() * config.baseMs;
    return Math.min(exp + jitter, config.maxMs);
}

/**
 * @param {unknown} err
 * @returns {boolean} true if ``err`` represents a transient failure
 *   worth retrying (network blip, server timeout) — never an
 *   RPCError (server-returned and deterministic) or a
 *   ConnectionAbortedError (caller intent).
 */
function isRetryable(err) {
    return (
        (err instanceof ConnectionLostError || err instanceof ConnectionTimeoutError) &&
        // Deterministic non-JSON-RPC responses (login-page redirect, 404 HTML,
        // captive portal) never change on retry.
        !(err instanceof InvalidResponseError)
    );
}

// In-flight deduplication

/**
 * Shared in-flight promises keyed by ``buildKey(url, params)``, used by the
 * ``settings.dedup`` branch of ``rpc._rpc`` so concurrent callers issuing the
 * same request (e.g. a form and its sidebar both reading ``res.partner`` [42])
 * share a single fetch. Entries evict on settle (success or rejection).
 *
 * Abort is shared across deduped callers: aborting the returned promise
 * cancels the underlying fetch, and every other caller sees a
 * ``ConnectionAbortedError`` too. Callers needing independent abort
 * lifecycles must not opt in to ``dedup``.
 *
 * Anchored on ``globalThis`` (see ``_rpcState``) so concurrent identical
 * requests dedupe across bundles too.
 *
 * @type {Map<string, Promise<any>>}
 */
const inflightDedup = _rpcState.inflightDedup;

/**
 * Fingerprint the behaviour-affecting settings so concurrent callers with the
 * same ``(url, params)`` but DIFFERENT settings don't join the same in-flight
 * promise — otherwise the second caller would silently inherit the first's
 * settings (e.g. a non-silent caller deduped onto a ``silent`` one loses its
 * loading indicator and error dialog).
 *
 * ``dedup`` itself is excluded (always set on this path). ``headers`` is
 * normalised to sorted entries so a plain-object and a ``Headers`` spelling
 * still match. ``cache.callback`` is dropped by ``JSON.stringify`` on
 * purpose — it only affects cache-hit notification, isolated in the cache
 * layer.
 *
 * Only a COLLISION (callers that must not share getting the same
 * fingerprint) is a real failure; a coarse fingerprint that SPLITS callers
 * that could have shared just costs a redundant fetch, so this errs toward
 * splitting.
 *
 * @param {{[key: string]: any}} settings
 * @returns {string}
 */
function dedupSettingsFingerprint(settings) {
    const parts = [];
    for (const key of [...RPC_SETTINGS].sort()) {
        if (key === "dedup" || settings[key] === undefined) {
            continue;
        }
        let value = settings[key];
        if (key === "headers") {
            value = [...new Headers(/** @type {any} */ (value)).entries()].sort();
        }
        parts.push(`${key}=${JSON.stringify(value)}`);
    }
    return parts.join("&");
}

// Main RPC
/**
 * @param {string} url
 * @param {{[key: string]: any}} [params]
 * @param {{[key: string]: any}} [settings]
 * @returns {any}
 */
export function rpc(url, params = {}, settings = {}) {
    return rpc._rpc(url, params, settings);
}
// such that it can be overriden in tests
/**
 * @param {string} url
 * @param {{[key: string]: any}} params
 * @param {{[key: string]: any}} settings
 * @returns {Promise<any>}
 */
rpc._rpc = function (url, params, settings) {
    validateRPCSettings(settings);
    if (settings.dedup) {
        // Outermost layer: identical concurrent (url, params) AND matching
        // settings share one promise. Composes with cache and retry via the
        // recursive ``rpc._rpc`` call with ``dedup`` stripped; the settings
        // fingerprint keeps differing callers from inheriting each other's
        // behaviour.
        const key = `${buildKey(url, params)}|${dedupSettingsFingerprint(settings)}`;
        const existing = inflightDedup.get(key);
        if (existing) {
            return existing;
        }
        const promise = rpc._rpc(url, params, omit(settings, "dedup"));
        inflightDedup.set(key, promise);
        // ``.then(onSettle, onSettle)`` instead of ``.finally`` so the chained
        // promise doesn't propagate the rejection (callers handle the original
        // ``promise``'s rejection; a parallel unhandled one would surface as an
        // unhandledRejection). The identity guard covers re-entrancy where a
        // synchronous re-registration could displace the entry.
        const onSettle = () => {
            if (inflightDedup.get(key) === promise) {
                inflightDedup.delete(key);
            }
        };
        promise.then(onSettle, onSettle);
        // Silent abort (``abort(false)``) leaves the outer promise pending, so
        // onSettle never fires via the then-chain and would leak this entry
        // forever. Wrap abort to evict the dedup slot synchronously.
        // ``abort(true)`` still works via the rejection-handler arm; the
        // wrapper is idempotent since onSettle guards on identity.
        const innerAbort = /** @type {any} */ (promise).abort;
        if (typeof innerAbort === "function") {
            /** @type {any} */ (promise).abort = function (rejectError = true) {
                onSettle();
                return innerAbort.call(this, rejectError);
            };
        }
        return promise;
    }
    if (settings.cache && _rpcState.rpcCache) {
        // Thread ``params.model`` into the cache settings so the entry joins
        // the per-table model→keys reverse index, making ``invalidateByModel``
        // O(1) instead of scanning every key. Non-call_kw endpoints (e.g.
        // session_info, get_views) have no model and stay reachable only via
        // ``invalidate(table)``.
        const cacheSettings =
            typeof settings.cache === "boolean" ? {} : { ...settings.cache };
        if (params?.model && cacheSettings.model === undefined) {
            cacheSettings.model = params.model;
        }
        // Preserve the ``RpcPromise`` contract on the cache path: ``cache.read``
        // yields a plain promise with no ``abort``, which would crash a caller
        // doing ``prom.abort(false)``. Capture the fallback's abort (only
        // created on a cache MISS) and forward to it; on a cache HIT it's a
        // safe no-op. ``bind`` snapshots the real abort before we overwrite
        // ``.abort`` below, avoiding self-recursion.
        /** @type {((rejectError?: boolean) => void) | null} */
        let innerAbort = null;
        const fallback = () => {
            const inner = /** @type {any} */ (
                rpc._rpc(url, params, omit(settings, "cache"))
            );
            if (typeof inner.abort === "function") {
                innerAbort = inner.abort.bind(inner);
            }
            return inner;
        };
        const cacheTable = params?.method || url;
        const cacheKey = buildKey(url, params); // key-order independent (rpc_dedup.js)
        const cacheProm = _rpcState.rpcCache.read(
            cacheTable,
            cacheKey,
            fallback,
            cacheSettings,
        );
        // ``fallback`` runs synchronously inside ``read()`` on a cache MISS, so
        // by now ``innerAbort`` is set iff THIS caller initiated the underlying
        // fetch (a real miss or ``update: "always"`` refresh). It is null for a
        // joiner that shared the initiator's still in-flight request, and for a
        // warm hit on an already-resolved entry — neither owns a fetch.
        if (innerAbort) {
            /** @type {any} */ (cacheProm).abort = function (rejectError = true) {
                // A silent abort leaves the fallback fetch pending forever, so
                // the cache's own settle-time bookkeeping never runs — evict the
                // cache-miss slot synchronously (mirrors the dedup layer) so the
                // key can be fetched fresh next time instead of wedging. Only the
                // INITIATOR may evict (the ``innerAbort`` identity guard): a
                // joiner calling ``abortPending`` would tear down the initiator's
                // live pendingRequests/RAM slot, orphaning its fetch.
                if (!rejectError) {
                    _rpcState.rpcCache?.abortPending(cacheTable, cacheKey);
                }
                // ``?.()`` is only for TS: innerAbort is non-null whenever this
                // wrapper exists (it is only installed inside the guard above,
                // and never reset), but closure assignments defeat narrowing.
                innerAbort?.(rejectError);
            };
            return cacheProm;
        }
        // Joiner / warm hit: no own fetch to abort. ``read()`` returned a plain
        // ``ramValue.then(shape)`` with no ``abort`` and no way to reject just
        // this caller. Wrap it so ``abort(true)`` honors the reject contract
        // (rejects THIS caller with ``ConnectionAbortedError``) without touching
        // the initiator's shared in-flight request. ``abort(false)`` stays a
        // silent cancel — the promise is left unsettled, matching the non-cached
        // ``abort(false)`` contract. Without this, an aborted joiner's promise
        // silently resolved with the shared value after the caller had torn down.
        let abortReject;
        const joinerProm = new Promise((resolve, reject) => {
            abortReject = reject;
            cacheProm.then(resolve, reject);
        });
        /** @type {any} */ (joinerProm).abort = function (rejectError = true) {
            if (rejectError) {
                abortReject(new ConnectionAbortedError(url));
            }
        };
        return joinerProm;
    }
    if (settings.retry) {
        return _rpcWithRetry(url, params, settings);
    }
    return _rpcOnce(url, params, settings);
};

/**
 * Single-attempt RPC.  Carries the fetch + abort + error-classification
 * logic.  Callers go through ``rpc._rpc`` (which adds cache and retry
 * orchestration); this helper is also the unit that retry loops drive.
 *
 * @param {string} url
 * @param {{[key: string]: any}} params
 * @param {{[key: string]: any}} settings
 * @returns {Promise<any>}
 */
function _rpcOnce(url, params, settings) {
    const data = {
        id: _rpcState.rpcId++,
        jsonrpc: "2.0",
        method: "call",
        params,
    };
    // Build a Headers object so callers can pass either a plain object
    // or a Headers; Content-Type always wins so JSON-RPC stays JSON.
    const requestHeaders = new Headers(settings.headers || {});
    requestHeaders.set("Content-Type", "application/json");
    // Outer promise drives caller-visible state; we don't return the raw
    // fetch promise because abort(false) must leave the caller's promise
    // un-resolved, which fetch's AbortError doesn't model.
    const controller = new AbortController();
    let aborted = false;
    // Optional opt-in timeout: combine the caller-controlled abort signal
    // with ``AbortSignal.timeout(ms)`` and distinguish the source in the
    // catch handler via ``timeoutSignal.aborted``.
    /** @type {AbortSignal | null} */
    const timeoutSignal = settings.timeout
        ? AbortSignal.timeout(settings.timeout)
        : null;
    const fetchSignal = timeoutSignal
        ? AbortSignal.any([controller.signal, timeoutSignal])
        : controller.signal;
    const { promise, resolve, reject } = Promise.withResolvers();
    // ``settled`` gates the outer promise's terminal state: once settled,
    // ``abort`` must become a no-op, since a second ``RPC:RESPONSE`` for this
    // ``data.id`` would double-emit to id-pairing observers (loading_indicator,
    // slow_rpc_service).
    let settled = false;
    const settleResolve = (/** @type {any} */ value) => {
        settled = true;
        resolve(value);
    };
    const settleReject = (/** @type {any} */ error) => {
        settled = true;
        reject(error);
    };
    rpcBus.trigger(RpcEvent.REQUEST, { data, url, settings });

    browser
        .fetch(url, {
            method: "POST",
            headers: requestHeaders,
            body: JSON.stringify(data),
            signal: fetchSignal,
        })
        .then(async (response) => {
            if (aborted) {
                // abort() fired its own RPC:RESPONSE; nothing more to do.
                return;
            }
            if (response.status >= 502 && response.status <= 504) {
                // 502 Bad Gateway / 503 Service Unavailable / 504 Gateway Timeout
                // — common when Odoo is behind a reverse proxy (nginx, etc.)
                const error = new ConnectionLostError(url);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                settleReject(error);
                return;
            }
            if (response.status === 413) {
                // If the request content size exceeds the limit set by a reverse
                // proxy (e.g. nginx), it returns an HTTP 413 with a non-JSON body.
                const error = new RequestEntityTooLargeError();
                rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                settleReject(error);
                return;
            }
            // A non-JSON content type with a 5xx status signals a werkzeug
            // HTML error page (``PoolError``/``OperationalError``) rather
            // than a JSON-RPC envelope; classify it as ``ServerOverloadError``
            // so the retry layer applies a longer backoff floor. Non-5xx
            // non-JSON responses are deterministic (fetch follows redirects,
            // so a session-expired POST lands on the HTML login page with a
            // 200; 404 pages and captive portals are similar) — those are
            // ``InvalidResponseError`` and never retried.
            const contentType = response.headers.get("content-type") || "";
            if (contentType && !/application\/json/i.test(contentType)) {
                const error =
                    response.status >= 500
                        ? new ServerOverloadError(url, response.status)
                        : new InvalidResponseError(url, response.status);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                settleReject(error);
                return;
            }
            let parsed;
            try {
                parsed = await response.json();
            } catch (err) {
                // ``abort()`` can land after the headers pass the guard above
                // but while the body is still streaming: it cancels the body
                // read, so ``response.json()`` rejects with an AbortError.
                // That is caller intent, not a malformed response — ``abort()``
                // already fired its own RPC:RESPONSE and decided the outer
                // promise's fate, so bail out here instead of fabricating an
                // InvalidResponseError (which would reject a silently-aborted
                // promise and pop a false "Session Expired" dialog).
                if (aborted) {
                    return;
                }
                // ``settings.timeout`` can fire here too: the timeout signal
                // passed to fetch also cancels an in-progress body read, so
                // ``response.json()`` rejects with a TimeoutError DOMException.
                // Classify it exactly like the outer fetch ``.catch`` below —
                // falling through to the status-based fallback would turn a
                // retryable timeout on a 200 response into a deterministic
                // InvalidResponseError (false "Session Expired" dialog, and
                // ``isRetryable`` would stop retrying it).
                if (err?.name === "TimeoutError" || timeoutSignal?.aborted) {
                    const error = new ConnectionTimeoutError(url, settings.timeout);
                    rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                    settleReject(error);
                    return;
                }
                // Malformed JSON body (or missing content-type). On a 5xx,
                // treat as transient connectivity failure — a retry with
                // default backoff is reasonable. Otherwise the response is
                // deterministic garbage (empty 200, truncated proxy body):
                // retrying can't help.
                const error =
                    response.status >= 500
                        ? new ConnectionLostError(url)
                        : new InvalidResponseError(url, response.status);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                settleReject(error);
                return;
            }
            if (aborted) {
                // Body finished parsing but an abort raced in during the await;
                // honor the abort's terminal decision rather than double-emitting
                // a success RPC:RESPONSE for this data.id.
                return;
            }
            if (!parsed.error) {
                // Plan-C envelope versioning: ``@versioned_envelope`` methods
                // (web/models/_versioning.py) lift a content hash to
                // ``parsed.version`` sibling-of-result. Re-attach it as
                // ``result.__version`` so the rpc cache's ``payloadChanged``
                // sees the same field regardless of in-payload vs out-of-band
                // stamping. Skips primitives and dicts already carrying it.
                const result = parsed.result;
                if (
                    parsed.version !== undefined &&
                    result &&
                    typeof result === "object" &&
                    result.__version === undefined
                ) {
                    result.__version = parsed.version;
                }
                rpcBus.trigger(RpcEvent.RESPONSE, {
                    data,
                    settings,
                    result,
                });
                settleResolve(result);
                return;
            }
            const error = makeErrorFromResponse(parsed.error);
            error.model = data.params.model;
            rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
            settleReject(error);
        })
        .catch((err) => {
            // fetch rejects with:
            //   • TypeError on network failure (DNS, CORS, server unreachable)
            //   • DOMException("AbortError") when controller.abort() fires
            //   • DOMException("TimeoutError") when AbortSignal.timeout() fires
            // The two abort paths must surface as different error classes;
            // ConnectionTimeoutError carries the configured timeoutMs so
            // callers can decide whether to retry, alert the user, etc.
            if (aborted) {
                // abort() fired its own RPC:RESPONSE; nothing more to do.
                return;
            }
            if (err?.name === "TimeoutError" || timeoutSignal?.aborted) {
                const error = new ConnectionTimeoutError(url, settings.timeout);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                settleReject(error);
                return;
            }
            if (err?.name === "AbortError") {
                // External abort (e.g. parent AbortController forwarded
                // through AbortSignal.any) — treat as caller-initiated.
                const error = new ConnectionAbortedError("fetch abort");
                rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                settleReject(error);
                return;
            }
            const error = new ConnectionLostError(url);
            rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
            settleReject(error);
        });

    /**
     * @param {boolean} rejectError Returns an error if true. Allows you to cancel
     *                  ignored rpc's in order to unblock the ui and not display an error.
     */
    /** @type {RpcPromise<any>} */ (promise).abort = function (rejectError = true) {
        if (settled || aborted) {
            // A second RPC:RESPONSE for this data.id would double-emit to
            // id-keyed observers (loading_indicator, slow_rpc_service).
            return;
        }
        aborted = true;
        controller.abort();
        const error = new ConnectionAbortedError("fetch abort");
        rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
        if (rejectError) {
            settleReject(error);
        }
        // rejectError=false: outer promise stays pending — caller asked to
        // silently cancel without surfacing an error to the UI.
    };
    return /** @type {RpcPromise<any>} */ (promise);
}

/**
 * Wrap {@link _rpcOnce} with exponential-backoff retry on transient
 * failures (ConnectionLostError, ConnectionTimeoutError).  Each attempt
 * fires its own ``RPC:REQUEST`` and ``RPC:RESPONSE`` on ``rpcBus`` so
 * observers see the real attempt count.
 *
 * Caller opts in via ``settings.retry``.  RPCError (server-returned and
 * deterministic) and ConnectionAbortedError (caller intent) are never
 * retried.
 *
 * @param {string} url
 * @param {{[key: string]: any}} params
 * @param {{[key: string]: any}} settings
 * @returns {Promise<any>}
 */
function _rpcWithRetry(url, params, settings) {
    const config = normalizeRetry(settings.retry);
    const innerSettings = omit(settings, "retry");
    const { promise, resolve, reject } = Promise.withResolvers();
    let aborted = false;
    let settled = false;
    /**
     * The current in-flight attempt, or ``null`` between attempts and after
     * settle. ``abort`` forwards only to a genuinely in-flight attempt —
     * aborting an already-settled one would emit a stray RPC:RESPONSE.
     *
     * @type {RpcPromise<unknown> | null}
     */
    let currentInner = null;
    /**
     * Handle of the scheduled backoff retry, or ``null`` when none is
     * pending. ``abort`` must ``clearTimeout`` it, or the retry fires after
     * the caller aborted and issues an unwanted RPC.
     *
     * @type {ReturnType<typeof browser.setTimeout> | null}
     */
    let backoffTimer = null;
    let attempt = 0;

    const settleResolve = (/** @type {any} */ value) => {
        settled = true;
        resolve(value);
    };
    const settleReject = (/** @type {any} */ error) => {
        settled = true;
        reject(error);
    };

    const tryOnce = () => {
        backoffTimer = null;
        if (aborted) {
            return;
        }
        attempt++;
        const inner = /** @type {RpcPromise<unknown>} */ (
            _rpcOnce(url, params, innerSettings)
        );
        currentInner = inner;
        inner.then(
            (/** @type {unknown} */ result) => {
                currentInner = null;
                if (!aborted) {
                    settleResolve(result);
                }
            },
            (/** @type {unknown} */ err) => {
                // This attempt is no longer in flight; clear the handle so a
                // concurrent abort neither re-aborts it nor forwards to a
                // settled promise.
                currentInner = null;
                if (aborted) {
                    return;
                }
                if (isRetryable(err) && attempt <= config.retries) {
                    backoffTimer = browser.setTimeout(
                        tryOnce,
                        backoffDelay(attempt, config, err),
                    );
                } else {
                    settleReject(err);
                }
            },
        );
    };

    /** @type {RpcPromise<any>} */ (promise).abort = function (rejectError = true) {
        if (settled || aborted) {
            return;
        }
        aborted = true;
        // Cancel a pending backoff retry: during the wait no attempt is in
        // flight, so without this the scheduled ``tryOnce`` would fire a fresh
        // RPC after the caller already gave up.
        if (backoffTimer !== null) {
            browser.clearTimeout(backoffTimer);
            backoffTimer = null;
        }
        // Forward to the in-flight attempt only (``currentInner`` is null
        // during backoff and after settle).  Its own abort fires the single
        // RPC:RESPONSE for that attempt's data.id.
        currentInner?.abort?.(rejectError);
        currentInner = null;
        if (rejectError) {
            settleReject(new ConnectionAbortedError("retry chain aborted"));
        }
        // rejectError=false: outer promise stays pending (silent abort).
    };

    tryOnce();
    return /** @type {RpcPromise<any>} */ (promise);
}
