// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc - JSON-RPC client built on fetch+AbortController, with error classification and request bus events */

import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { buildKey } from "@web/core/network/rpc_dedup";
import { rpcLog } from "@web/core/utils/asset_log";
import { isObject, omit } from "@web/core/utils/collections/objects";
import { globalSingleton } from "@web/core/utils/global_singleton";

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
 * ``url`` is set on BOTH events. It used to be omitted from every RESPONSE
 * trigger, which left observers unable to identify the endpoint of any call
 * whose ``params`` carry no ``model``/``method`` — session_info,
 * ``/web/action/load``, ``get_views``, the observability beacons. The debug
 * RPC log below is one such consumer: its fallback ``params.method ||
 * detail.url`` rendered a literal ``"undefined"`` for those calls.
 *
 * @typedef {{
 *  data: { id: number; jsonrpc: "2.0"; method: "call"; params: Record<string, any> };
 *  url: string;
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

/** @type {{ rpcBus: EventBus, inflightDedup: Map<string, Promise<any>>, rpcCache: RPCCache | null | undefined, busListenersAttached: boolean, rpcId: number, dedupCallbackSeq: number }} */
const _rpcState = globalSingleton("rpc", () => ({
    rpcBus: new EventBus(),
    inflightDedup: new Map(),
    rpcCache: undefined,
    busListenersAttached: false,
    rpcId: 0,
    dedupCallbackSeq: 0,
}));

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
 * Classify a transport failure into the error taxonomy above.
 *
 * Shared by the two paths that can see one — the ``fetch()`` rejection and the
 * ``response.json()`` rejection — so an interrupted transfer yields the same
 * error whether it dies before or after the response headers arrive. They used
 * to classify independently, and disagreed: a transfer cut mid-body became an
 * ``InvalidResponseError``, which {@link isRetryable} excludes as deterministic,
 * while the very same interruption arriving one tick earlier became a retryable
 * ``ConnectionLostError``.
 *
 * ``response`` is passed only by the body path, and enables the one genuinely
 * deterministic case: a body that fully arrived and is not JSON (an HTML login
 * page served with a JSON content type, an empty 200). That is a ``SyntaxError``
 * from the parser; anything else means the transfer itself failed.
 *
 * @param {any} err
 * @param {string} url
 * @param {{[key: string]: any}} settings
 * @param {AbortSignal | null} timeoutSignal
 * @param {Response} [response] set by the body-read path only
 * @returns {Error}
 */
function classifyTransportFailure(err, url, settings, timeoutSignal, response) {
    if (err?.name === "TimeoutError" || timeoutSignal?.aborted) {
        return new ConnectionTimeoutError(url, settings.timeout);
    }
    if (err?.name === "AbortError") {
        return new ConnectionAbortedError("fetch abort");
    }
    if (response && response.status < 500 && err?.name === "SyntaxError") {
        return new InvalidResponseError(url, response.status);
    }
    return new ConnectionLostError(url);
}

/**
 * @param {JsonRpcError} response
 * @returns {RPCError}
 */
export function makeErrorFromResponse(response) {
    const { code, data: errorData, message, type: subType } = response;
    const error = new RPCError();
    error.exceptionName = errorData?.name ?? null;
    error.subType = subType ?? null;
    error.data = errorData ?? null;
    error.message = message;
    error.code = code;
    return error;
}

/**
 * @param {RPCCache} cache
 */
rpc.setCache = function (cache) {
    _rpcState.rpcCache = cache;
};

if (!_rpcState.busListenersAttached) {
    _rpcState.busListenersAttached = true;

    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, (event) => {
        /** @type {{ tables?: string[]; model?: string } | string | string[] | undefined} */
        const detail = /** @type {CustomEvent<any>} */ (event).detail;
        if (isObject(detail)) {
            const objDetail = /** @type {{ tables?: string[]; model?: string }} */ (
                detail
            );
            if (objDetail.model) {
                _rpcState.rpcCache?.invalidateByModel(
                    /** @type {string[]} */ (objDetail.tables),
                    objDetail.model,
                );
            } else {
                _rpcState.rpcCache?.invalidate(objDetail.tables ?? null);
            }
            return;
        }
        _rpcState.rpcCache?.invalidate(
            /** @type {string | string[] | null} */ (detail ?? null),
        );
    });

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
        !(err instanceof InvalidResponseError)
    );
}

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
    const cache = settings.cache;
    if (cache && typeof cache === "object" && typeof cache.callback === "function") {
        parts.push(`cb=${_rpcState.dedupCallbackSeq++}`);
    }
    return parts.join("&");
}

/**
 * @param {string} url
 * @param {{[key: string]: any}} [params]
 * @param {{[key: string]: any}} [settings]
 * @returns {any}
 */
export function rpc(url, params = {}, settings = {}) {
    return rpc._rpc(url, params, settings);
}
/**
 * @param {string} url
 * @param {{[key: string]: any}} params
 * @param {{[key: string]: any}} settings
 * @returns {Promise<any>}
 */
rpc._rpc = function (url, params, settings) {
    validateRPCSettings(settings);
    if (settings.dedup) {
        const key = `${buildKey(url, params)}|${dedupSettingsFingerprint(settings)}`;
        const existing = inflightDedup.get(key);
        if (existing) {
            return existing;
        }
        const promise = rpc._rpc(url, params, omit(settings, "dedup"));
        inflightDedup.set(key, promise);
        const onSettle = () => {
            if (inflightDedup.get(key) === promise) {
                inflightDedup.delete(key);
            }
        };
        promise.then(onSettle, onSettle);
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
        const cacheSettings =
            typeof settings.cache === "boolean" ? {} : { ...settings.cache };
        if (params?.model && cacheSettings.model === undefined) {
            cacheSettings.model = params.model;
        }
        cacheSettings.silent = settings.silent;
        let callerAborted = false;
        if (typeof cacheSettings.callback === "function") {
            const userCallback = cacheSettings.callback;
            cacheSettings.callback = (/** @type {any[]} */ ...args) => {
                if (!callerAborted) {
                    userCallback(...args);
                }
            };
        }
        /** @type {((rejectError?: boolean) => void) | null} */
        let innerAbort = null;
        let ownRequest = null;
        const fallback = (/** @type {object} */ request) => {
            ownRequest = request ?? null;
            const inner = /** @type {any} */ (
                rpc._rpc(url, params, omit(settings, "cache"))
            );
            if (typeof inner.abort === "function") {
                innerAbort = inner.abort.bind(inner);
            }
            return inner;
        };
        const cacheTable = params?.method || url;
        const cacheKey = buildKey(url, params);
        const cacheProm = _rpcState.rpcCache.read(
            cacheTable,
            cacheKey,
            fallback,
            cacheSettings,
        );
        if (innerAbort) {
            /** @type {any} */ (cacheProm).abort = function (rejectError = true) {
                callerAborted = true;
                if (!rejectError) {
                    _rpcState.rpcCache?.abortPending(cacheTable, cacheKey, ownRequest);
                }
                innerAbort?.(rejectError);
            };
            return cacheProm;
        }
        let abortReject;
        const joinerProm = new Promise((resolve, reject) => {
            abortReject = reject;
            cacheProm.then(resolve, (error) => {
                if (!callerAborted) {
                    reject(error);
                }
            });
        });
        /** @type {any} */ (joinerProm).abort = function (rejectError = true) {
            callerAborted = true;
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
    const requestHeaders = new Headers(settings.headers || {});
    requestHeaders.set("Content-Type", "application/json");
    const controller = new AbortController();
    let aborted = false;
    /** @type {AbortSignal | null} */
    const timeoutSignal = settings.timeout
        ? AbortSignal.timeout(settings.timeout)
        : null;
    const fetchSignal = timeoutSignal
        ? AbortSignal.any([controller.signal, timeoutSignal])
        : controller.signal;
    const { promise, resolve, reject } = Promise.withResolvers();
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
                return;
            }
            if (response.status >= 502 && response.status <= 504) {
                const error = new ServerOverloadError(url, response.status);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, url, settings, error });
                settleReject(error);
                return;
            }
            if (response.status === 413) {
                const error = new RequestEntityTooLargeError();
                rpcBus.trigger(RpcEvent.RESPONSE, { data, url, settings, error });
                settleReject(error);
                return;
            }
            const contentType = response.headers.get("content-type") || "";
            if (contentType && !/application\/json/i.test(contentType)) {
                const error =
                    response.status >= 500
                        ? new ServerOverloadError(url, response.status)
                        : new InvalidResponseError(url, response.status);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, url, settings, error });
                settleReject(error);
                return;
            }
            let parsed;
            try {
                parsed = await response.json();
            } catch (err) {
                if (aborted) {
                    return;
                }
                const error = classifyTransportFailure(
                    err,
                    url,
                    settings,
                    timeoutSignal,
                    response,
                );
                rpcBus.trigger(RpcEvent.RESPONSE, { data, url, settings, error });
                settleReject(error);
                return;
            }
            if (aborted) {
                return;
            }
            if (!parsed.error && !response.ok) {
                const error =
                    response.status >= 500
                        ? new ServerOverloadError(url, response.status)
                        : new InvalidResponseError(url, response.status);
                rpcBus.trigger(RpcEvent.RESPONSE, { data, url, settings, error });
                settleReject(error);
                return;
            }
            if (!parsed.error) {
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
                    url,
                    settings,
                    result,
                });
                settleResolve(result);
                return;
            }
            const error = makeErrorFromResponse(parsed.error);
            error.model = data.params.model;
            rpcBus.trigger(RpcEvent.RESPONSE, { data, url, settings, error });
            settleReject(error);
        })
        .catch((err) => {
            if (aborted) {
                return;
            }
            const error = classifyTransportFailure(err, url, settings, timeoutSignal);
            rpcBus.trigger(RpcEvent.RESPONSE, { data, url, settings, error });
            settleReject(error);
        });

    /**
     * @param {boolean} rejectError Returns an error if true. Allows you to cancel
     *                  ignored rpc's to unblock the ui and not display an error.
     */
    /** @type {RpcPromise<any>} */ (promise).abort = function (rejectError = true) {
        if (settled || aborted) {
            return;
        }
        aborted = true;
        controller.abort();
        const error = new ConnectionAbortedError("fetch abort");
        rpcBus.trigger(RpcEvent.RESPONSE, { data, url, settings, error });
        if (rejectError) {
            settleReject(error);
        }
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
        if (backoffTimer !== null) {
            browser.clearTimeout(backoffTimer);
            backoffTimer = null;
        }
        currentInner?.abort?.(rejectError);
        currentInner = null;
        if (rejectError) {
            settleReject(new ConnectionAbortedError("retry chain aborted"));
        }
    };

    tryOnce();
    return /** @type {RpcPromise<any>} */ (promise);
}
