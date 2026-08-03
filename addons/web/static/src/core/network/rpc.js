// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc */

import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { buildKey } from "@web/core/network/rpc_dedup";
import { rpcLog } from "@web/core/utils/asset_log";
import { isObject, omit } from "@web/core/utils/collections/objects";
import { globalSingleton } from "@web/core/utils/global_singleton";

/** @import { RPCCache } from "@web/core/network/rpc_cache" */

/**
 * @typedef {{
 *  code: number;
 *  message: string;
 *  data?: RPCErrorData;
 *  type?: string;
 * }} JsonRpcError
 */

/**
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
 * @typedef {{
 *  data: { id: number; jsonrpc: "2.0"; method: "call"; params: Record<string, any> };
 *  url: string;
 *  settings?: RpcSettings;
 *  result?: any;
 *  error?: NetworkError;
 * }} RpcEventDetail
 */

/**
 * @template T
 * @typedef {Promise<T> & { abort: (rejectError?: boolean) => void }} RpcPromise
 */

/**
 * @typedef {{
 *  rpcBus: EventBus,
 *  inflightDedup: Map<string, { shared: any, subscribers: number }>,
 *  rpcCache: RPCCache | null | undefined,
 *  busListenersAttached: boolean,
 *  rpcId: number,
 *  dedupCallbackSeq: number,
 * }} RpcState
 */

/**
 * The factory's return type is annotated rather than the binding: the literal
 * is inferred on its own, so a `@type` on `_rpcState` alone leaves `rpcCache`
 * implicitly `any`.
 *
 * @type {RpcState}
 */
const _rpcState = globalSingleton(
    "rpc",
    () =>
        /** @type {RpcState} */ ({
            rpcBus: new EventBus(),
            inflightDedup: new Map(),
            rpcCache: undefined,
            busListenersAttached: false,
            rpcId: 0,
            dedupCallbackSeq: 0,
        }),
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

export class NetworkError extends Error {
    // Behaviour-as-data: whether an automatic retry could plausibly succeed.
    // Consumers gate on this rather than on the class, so a new error type
    // declares its own retryability instead of every retry site special-casing
    // it. Default: not retryable.
    retryable = false;
}

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
         * @type {string | undefined}
         */
        this.model = undefined;
    }
}

export class ConnectionLostError extends NetworkError {
    // A dropped/unestablished connection: retrying may reach the server.
    retryable = true;

    /**
     * @param {string} [url]
     * @param {...any} args
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

export class ServerOverloadError extends ConnectionLostError {
    /**
     * @param {string} url
     * @param {number} status
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

// NOT a ConnectionLostError: a well-formed HTTP response arrived, it just was
// not the JSON-RPC we expected (e.g. a session-expired request redirected to a
// login page). It is a distinct failure, so it extends NetworkError directly and
// stays `retryable = false` -- the connection is fine, retrying returns the same
// non-JSON. Consumers that must still react to it (the session-expired handler,
// spreadsheet collaboration, POS sync) name it explicitly rather than relying on
// a `ConnectionLostError` is-a they would otherwise all have to carve back out.
export class InvalidResponseError extends NetworkError {
    /**
     * @param {string} url
     * @param {number} status
     * @param {...any} args
     */
    constructor(url, status, ...args) {
        const message = url
            ? `Server returned an invalid (non JSON-RPC) response (HTTP ${status}) at "${url}"`
            : `Server returned an invalid (non JSON-RPC) response (HTTP ${status})`;
        super(message, ...args);
        this.name = "InvalidResponseError";
        /** @type {number} */
        this.status = status;
        /** @type {string | undefined} */
        this.url = url;
    }
}

export class ConnectionAbortedError extends NetworkError {
    name = "ConnectionAbortedError";
}

export class RequestEntityTooLargeError extends NetworkError {
    constructor() {
        super(
            "The request you sent exceeded the maximum size limit configured on the server",
        );
        this.name = "RequestEntityTooLargeError";
    }
}

export class ConnectionTimeoutError extends NetworkError {
    // A request that timed out: a fresh attempt may complete in time.
    retryable = true;

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
 * @param {any} err
 * @param {string} url
 * @param {{[key: string]: any}} settings
 * @param {AbortSignal | null} timeoutSignal
 * @param {Response} [response]
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

/**
 * Delete the persisted RPC cache (its IndexedDB store). Used on logout so a
 * user's cached data does not outlive their session on a shared browser. A no-op
 * that resolves when no disk cache is configured.
 *
 * @returns {Promise<void>}
 */
rpc.purgeCacheStorage = function () {
    return _rpcState.rpcCache?.purgeStorage() ?? Promise.resolve();
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

const SERVER_OVERLOAD_BACKOFF_FLOOR_MS = 1000;

/**
 * @param {number} attempt
 * @param {RetryConfig} config
 * @param {unknown} [lastError]
 * @returns {number}
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
 * @returns {boolean}
 */
function isRetryable(err) {
    // Behaviour-as-data: each NetworkError declares its own retryability, so this
    // gate no longer enumerates types and carves InvalidResponseError back out
    // (ConnectionLost/Timeout/ServerOverload are `retryable`; InvalidResponse and
    // aborts are not).
    return err instanceof NetworkError && err.retryable === true;
}

/**
 * In-flight requests shared by ``dedup`` callers.
 *
 * Each caller gets its own promise over the shared request and its own
 * ``abort``, which detaches that caller only; the underlying request is
 * cancelled when the last subscriber leaves. Handing the shared promise out
 * directly made one caller's ``abort()`` reject every other caller.
 *
 * @type {Map<string, { shared: any, subscribers: number }>}
 */
const inflightDedup = _rpcState.inflightDedup;

/**
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
        let entry = inflightDedup.get(key);
        if (!entry) {
            const shared = /** @type {any} */ (
                rpc._rpc(url, params, omit(settings, "dedup"))
            );
            entry = { shared, subscribers: 0 };
            const onSettle = () => {
                if (inflightDedup.get(key) === entry) {
                    inflightDedup.delete(key);
                }
            };
            shared.then(onSettle, onSettle);
            inflightDedup.set(key, entry);
        }
        const joined = entry;
        joined.subscribers++;
        let detached = false;
        const { promise, resolve, reject } = Promise.withResolvers();
        joined.shared.then(
            (/** @type {any} */ result) => {
                if (!detached) {
                    resolve(result);
                }
            },
            (/** @type {any} */ error) => {
                if (!detached) {
                    reject(error);
                }
            },
        );
        /** @type {any} */ (promise).abort = function (rejectError = true) {
            if (detached) {
                return;
            }
            detached = true;
            if (--joined.subscribers === 0) {
                if (inflightDedup.get(key) === joined) {
                    inflightDedup.delete(key);
                }
                joined.shared.abort?.(false);
            }
            if (rejectError) {
                reject(new ConnectionAbortedError(url));
            }
        };
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
        /** @type {object | null} */
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
        /** @type {(reason?: any) => void} */
        let abortReject = () => {};
        const joinerProm = new Promise((resolve, reject) => {
            abortReject = reject;
            cacheProm.then(resolve, (/** @type {any} */ error) => {
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
     * @param {boolean} rejectError
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
     * @type {RpcPromise<unknown> | null}
     */
    let currentInner = null;
    /**
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
