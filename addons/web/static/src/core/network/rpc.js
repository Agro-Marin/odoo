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
 * Structured payload Odoo embeds in ``JsonRpcError.data``. The shape is
 * stable in practice — every downstream consumer (``error_handlers``,
 * ``error_dialogs``, ``form_controller`` error rendering,
 * ``file_upload_service`` failure messaging, ``domain_field`` KeyError
 * narrowing) reads from this fixed surface, even though server code
 * may append addon-specific keys via the index signature.
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
// ``rpcBus``, the in-flight dedup map, and the ``rpcCache`` slot MUST be
// shared by every ESM bundle in the document, for the same reason
// ``registry.js`` (``__odooRegistry__``), ``templates.js``
// (``__odooTemplates__``) and ``l10n/translation.js`` anchor their state
// on ``globalThis``: esbuild inlines this module into ``web.assets_web``
// and every dynamic child bundle, and per-copy module state would give
// each bundle its own bus (listeners in one bundle never see RPCs fired
// from another), its own dedup map (no dedup across bundles), and its own
// cache slot (``rpc.setCache`` from the parent leaves satellites
// uncached).  ``??=`` keeps the FIRST bundle's instance authoritative.
const _RPC_STATE_KEY = "__odoo_rpc_state__";
/** @type {{ rpcBus: EventBus, inflightDedup: Map<string, Promise<any>>, rpcCache: RPCCache | null | undefined, busListenersAttached: boolean, rpcId: number }} */
const _rpcState = /** @type {any} */ (
    globalThis[_RPC_STATE_KEY] ??= {
        rpcBus: new EventBus(),
        inflightDedup: new Map(),
        rpcCache: undefined,
        busListenersAttached: false,
        // Monotonic ``data.id`` source shared across every ESM bundle in the
        // document.  MUST live on the cross-bundle singleton (not a module-level
        // ``let``): esbuild inlines this module into every child bundle, so a
        // per-copy counter would restart at 0 in each bundle while they all share
        // one ``rpcBus`` — two live RPCs from different bundles would then collide
        // on the same ``data.id``, conflating them for every bus observer that
        // keys by ``data.id`` (loading_indicator, slow_rpc_service).
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

// -----------------------------------------------------------------------------
// Errors
// -----------------------------------------------------------------------------

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
 * werkzeug-rendered HTML error page from ``PoolError``,
 * ``OperationalError``, or other unhandled controller exception).
 *
 * Distinct from ``ConnectionLostError`` (which carries the same
 * meaning to legacy callers that don't branch on the subclass) so
 * that retry logic can apply a longer backoff floor — retrying too
 * fast against an overloaded backend contributes to the overload.
 *
 * Extends ``ConnectionLostError`` for backward compatibility: every
 * existing ``e instanceof ConnectionLostError`` catch still matches.
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

// -----------------------------------------------------------------------------
// Cache RPC method
// -----------------------------------------------------------------------------

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
            // ``isObject`` is more selective than ``typeof === "object"``
            // (rejects Map/Set/Date/Array) but TS doesn't see it as a type
            // predicate. Re-cast to the model-scoped shape so the property
            // accesses below typecheck.
            //
            // Note: ``tables`` is cast as ``string[]`` (non-optional) — the
            // contract documented at every emit site is "if model is set,
            // tables is set" (see ``RESULT_SET_TABLES`` in
            // ``services/result_set_cache_invalidator_service.js``). The
            // cache's ``invalidateByModel`` iterates ``tables`` and would
            // throw on ``undefined`` regardless, so preserving the old
            // throw-on-malformed-emit behavior is correct.
            const objDetail = /** @type {{ tables: string[]; model?: string }} */ (
                detail
            );
            if (objDetail.model) {
                _rpcState.rpcCache?.invalidateByModel(
                    objDetail.tables,
                    objDetail.model,
                );
                return;
            }
        }
        // ``detail`` is either ``string`` (single table — most emit sites
        // pass a literal table name like ``"get_views"``), ``string[]``
        // (rare, accepted by the cache for batch clearing), or
        // ``undefined`` (full-cache nuke from ``webclient.js`` after
        // service-worker registration). The cache's ``invalidate``
        // accepts all three.
        _rpcState.rpcCache?.invalidate(
            /** @type {string | string[] | null} */ (detail ?? null),
        );
    });

    // -----------------------------------------------------------------------
    // Observability — passive bus listeners that mirror every RPC into the
    // rpcLog namespace.  Activated by ``localStorage.setItem("debug.rpc", "1")``
    // (or ``?debug=rpc``).  When disabled the listener body short-circuits on
    // rpcLog.enabled() before any payload construction — cost is one event
    // dispatch per RPC, negligible against the network round-trip itself.
    // -----------------------------------------------------------------------

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

// -----------------------------------------------------------------------------
// Retry helpers
// -----------------------------------------------------------------------------

/**
 * @typedef {{ retries: number; baseMs: number; maxMs: number }} RetryConfig
 */

/**
 * Normalize the user-supplied ``retry`` setting to a full {@link RetryConfig}.
 *
 * Accepts either a number (interpreted as ``retries``) or a partial
 * config object.  Defaults are tuned for transient infrastructure
 * failures (proxy hiccup, pool exhaustion, worker restart): three
 * attempts on top of the first, ramping from 200ms up to 2s.
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
 * Minimum delay applied between retries against an overloaded backend
 * (``ServerOverloadError``).  Retrying too aggressively against a
 * server that is already returning HTML error pages contributes to
 * the overload; the floor gives the worker pool / DB connections
 * time to drain before the next attempt.
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
    return err instanceof ConnectionLostError || err instanceof ConnectionTimeoutError;
}

// -----------------------------------------------------------------------------
// In-flight deduplication
// -----------------------------------------------------------------------------

/**
 * Shared in-flight promises keyed by ``buildKey(url, params)``.  Used by the
 * ``settings.dedup`` branch of ``rpc._rpc`` so two concurrent callers
 * issuing the same request (e.g., a form and its sidebar both reading
 * ``res.partner`` [42]) share a single fetch instead of firing twice.
 * Entries evict on settle (success OR rejection); a subsequent call
 * after settle fires fresh.
 *
 * Abort semantics are intentionally shared across deduped callers: if
 * any caller aborts the returned promise, the underlying fetch is
 * canceled and every other caller observing the same promise sees a
 * ``ConnectionAbortedError``.  This matches the common case — when
 * navigation cancels one in-flight read, the other component reading
 * the same record is usually on the same page being torn down — but
 * callers that need independent abort lifecycles must not opt in to
 * ``dedup``.
 *
 * Anchored on ``globalThis`` (see ``_rpcState``) so concurrent identical
 * requests dedupe across bundles too.
 *
 * @type {Map<string, Promise<any>>}
 */
const inflightDedup = _rpcState.inflightDedup;

/**
 * Fingerprint the behaviour-affecting settings so two concurrent callers
 * with identical ``(url, params)`` but DIFFERENT settings do NOT join onto
 * the same in-flight promise.  Without this, the second caller silently
 * inherits the FIRST caller's settings AND behaviour — e.g. a non-silent
 * caller deduped onto a ``silent`` one gets no loading indicator and no
 * error dialog, and a caller expecting ``retry``/``timeout`` gets the
 * other's policy instead.
 *
 * The ``dedup`` flag itself is excluded (always set on this path).
 * ``headers`` is normalised to sorted entries so a plain-object and a
 * ``Headers`` spelling of the same headers still match.  A
 * ``cache.callback`` function is dropped by ``JSON.stringify`` on purpose:
 * it does not change the fetch, only cache-hit notification, and callback
 * isolation is handled inside the cache layer.
 *
 * Only failure mode that matters is a COLLISION (two callers that must not
 * share getting the same fingerprint).  A coarse fingerprint that instead
 * SPLITS callers that could have shared is safe — it merely costs a
 * redundant fetch — so this errs deliberately on the side of splitting.
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

// -----------------------------------------------------------------------------
// Main RPC
// -----------------------------------------------------------------------------
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
        // settings share one promise.  Composes with cache and retry (they
        // run inside this branch via the recursive ``rpc._rpc`` call with
        // ``dedup`` stripped).  The settings fingerprint is folded into the
        // key so callers differing only by ``silent``/``cache``/``retry``/
        // ``timeout``/``headers`` never inherit each other's behaviour.
        const key = `${buildKey(url, params)}|${dedupSettingsFingerprint(settings)}`;
        const existing = inflightDedup.get(key);
        if (existing) {
            return existing;
        }
        const promise = rpc._rpc(url, params, omit(settings, "dedup"));
        inflightDedup.set(key, promise);
        // Evict on settle.  We use ``.then(onSettle, onSettle)`` instead of
        // ``.finally`` because the chained promise must not propagate the
        // rejection — callers handle the original ``promise``'s rejection
        // themselves, and a parallel unhandled chained rejection would
        // surface as an ``unhandledRejection`` event (which hoot reports
        // as an unverified error).  Both handlers return undefined, so
        // the derivative resolves cleanly regardless of outcome.  The
        // identity guard handles pathological re-entrancy where a
        // synchronous re-registration could displace the entry.
        const onSettle = () => {
            if (inflightDedup.get(key) === promise) {
                inflightDedup.delete(key);
            }
        };
        promise.then(onSettle, onSettle);
        // Silent abort path (``abort(false)``) cancels the underlying fetch
        // but leaves the outer promise pending — onSettle would never fire
        // via the then-chain, leaking this entry forever.  Wrap abort so
        // it evicts the dedup slot synchronously.  Without this, a
        // subsequent identical request would be deduped onto a
        // forever-pending promise (its fetch already canceled) and the
        // new caller would never see data.  ``abort(true)`` still works
        // via the rejection-handler arm of the then-chain; the wrapper
        // is idempotent because onSettle guards on identity.
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
        // Thread ``params.model`` into the cache settings so the entry
        // joins the per-table model→keys reverse index.  This makes
        // ``invalidateByModel`` O(1) instead of scanning + parsing
        // every key.  ``params.model`` is undefined for non-call_kw
        // endpoints (session_info, /web/action/load, get_views, ...);
        // those entries simply skip indexing and remain reachable only
        // via ``invalidate(table)``, which is how they're invalidated
        // today regardless.
        const cacheSettings =
            typeof settings.cache === "boolean" ? {} : { ...settings.cache };
        if (params?.model && cacheSettings.model === undefined) {
            cacheSettings.model = params.model;
        }
        // Preserve the ``RpcPromise`` contract on the cache path: the typedef
        // promises ``.abort()`` on EVERY ``rpc()`` return, but ``cache.read``
        // yields a plain promise with no ``abort`` — so a caller doing
        // ``prom.abort(false)`` on a cache-enabled call (e.g.
        // record_autocomplete.js) would crash on ``undefined``.  We capture
        // the underlying fallback's abort (created only on a cache MISS) and
        // forward to it.  On a cache HIT the fallback never runs, so ``abort``
        // is a safe no-op — there is no in-flight fetch to cancel.  ``bind``
        // snapshots the real abort before we overwrite ``.abort`` below, so
        // even if ``read`` returns the fallback promise itself there is no
        // self-recursion.
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
        const cacheProm = _rpcState.rpcCache.read(
            params?.method || url, // table
            buildKey(url, params), // key — key-order independent (rpc_dedup.js)
            fallback,
            cacheSettings,
        );
        /** @type {any} */ (cacheProm).abort = function (rejectError = true) {
            innerAbort?.(rejectError);
        };
        return cacheProm;
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
    // Outer promise drives caller-visible state.  We don't return the
    // raw fetch promise because abort(false) must leave the caller's
    // promise un-resolved, which fetch's AbortError doesn't model.
    const controller = new AbortController();
    let aborted = false;
    // Optional opt-in timeout.  Combine the caller-controlled abort
    // signal with ``AbortSignal.timeout(ms)`` so either source can
    // cancel the fetch.  We distinguish in the catch handler by
    // checking ``timeoutSignal.aborted``.
    /** @type {AbortSignal | null} */
    const timeoutSignal = settings.timeout
        ? AbortSignal.timeout(settings.timeout)
        : null;
    const fetchSignal = timeoutSignal
        ? AbortSignal.any([controller.signal, timeoutSignal])
        : controller.signal;
    const { promise, resolve, reject } = Promise.withResolvers();
    // ``settled`` gates the outer promise's terminal state.  Once the fetch
    // has resolved/rejected (or a previous abort settled it), ``abort`` must
    // become a no-op: firing another ``RPC:RESPONSE`` for this ``data.id``
    // would double-emit to observers that pair REQUEST/RESPONSE by id
    // (loading_indicator, slow_rpc_service), corrupting their bookkeeping.
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
            // Server-overload detection: a non-JSON content type signals that
            // the server returned an error page (typically werkzeug's HTML
            // traceback for ``PoolError`` / ``OperationalError``) rather than
            // a JSON-RPC envelope.  Classifying it as ``ServerOverloadError``
            // (subclass of ``ConnectionLostError`` for backward compat) lets
            // the retry layer apply a longer backoff floor so retries don't
            // pile onto an already-struggling backend.
            const contentType = response.headers.get("content-type") || "";
            if (contentType && !/application\/json/i.test(contentType)) {
                const error = new ServerOverloadError(url, response.status);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                settleReject(error);
                return;
            }
            let parsed;
            try {
                parsed = await response.json();
            } catch {
                // Genuinely-malformed JSON body despite an
                // ``application/json`` content-type header, or no content-type
                // at all.  Treated as transient connectivity failure: the
                // server didn't produce a recognisable response and a retry
                // with default backoff is reasonable.
                const error = new ConnectionLostError(url);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
                settleReject(error);
                return;
            }
            if (!parsed.error) {
                // Plan-C envelope versioning: server methods decorated with
                // ``@versioned_envelope`` (web/models/_versioning.py) stash a
                // content hash on ``request._response_version``, which the
                // dispatcher lifts to ``parsed.version`` sibling-of-result.  We
                // re-attach it as ``result.__version`` so the rpc cache's
                // ``payloadChanged`` sees the same field whether the server
                // used in-payload (@versioned) or out-of-band (@versioned_envelope)
                // stamping.  Skips primitives (no place to attach a property)
                // and dicts that already carry ``__version`` (in-payload path).
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
            // Already settled (fetch resolved/rejected) or already aborted:
            // do nothing.  Firing a second RPC:RESPONSE for this data.id here
            // would double-emit to id-keyed observers (loading_indicator,
            // slow_rpc_service); the pairing invariant must hold exactly once.
            return;
        }
        aborted = true;
        controller.abort();
        const error = new ConnectionAbortedError("fetch abort");
        rpcBus.trigger(RpcEvent.RESPONSE, { data, settings, error });
        if (rejectError) {
            settleReject(error);
        }
        // rejectError=false: outer promise stays pending — caller asked
        // to silently cancel without surfacing an error to the UI.
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
     * The current in-flight attempt, or ``null`` between attempts (during
     * the backoff wait) and after settle.  ``abort`` forwards ONLY to a
     * genuinely in-flight attempt — calling ``.abort()`` on an already-settled
     * attempt would emit a stray RPC:RESPONSE for its (already-paired)
     * data.id.
     *
     * @type {RpcPromise<unknown> | null}
     */
    let currentInner = null;
    /**
     * Handle of the scheduled backoff retry, or ``null`` when no retry is
     * pending.  ``abort`` must ``clearTimeout`` it, otherwise the retry fires
     * after the caller aborted and issues a fresh, unwanted RPC.
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
