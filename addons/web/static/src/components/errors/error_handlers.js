// @ts-check
/** @odoo-module native */

/** @module @web/components/errors/error_handlers */

/**
 * @typedef {import("@web/env").OdooEnv} OdooEnv
 * @typedef {import("@web/core/errors/uncaught_errors").UncaughtError} UncaughtError
 */
import {
    ClientErrorDialog,
    ErrorDialog,
    NetworkErrorDialog,
    RequestEntityTooLargeErrorDialog,
    RPCErrorDialog,
    SessionExpiredDialog,
} from "@web/components/errors/error_dialogs";
import { browser } from "@web/core/browser/browser";
import {
    ThirdPartyScriptError,
    UncaughtClientError,
    UncaughtPromiseError,
} from "@web/core/errors/error_service";
import {
    ConnectionLostError,
    InvalidResponseError,
    RequestEntityTooLargeError,
    rpc,
    RPCError,
} from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { SupersededError } from "@web/core/utils/concurrency";

const errorHandlerRegistry = registry.category("error_handlers");
const errorDialogRegistry = registry.category("error_dialogs");
const errorNotificationRegistry = registry.category("error_notifications");

errorDialogRegistry.addValidation((entry) => typeof entry === "function");

errorNotificationRegistry.addValidation({
    title: { type: [String, Object], optional: true },
    message: { type: [String, Object], optional: true },
    type: { type: String, optional: true },
    sticky: { type: Boolean, optional: true },
    buttons: { type: Array, optional: true },
    "*": true,
});

/**
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @param {Error} originalError
 * @returns {boolean}
 */
export function supersededErrorHandler(env, error, originalError) {
    if (originalError instanceof SupersededError || error instanceof SupersededError) {
        /** @type {any} */ (error).event?.preventDefault?.();
        return true;
    }
    return false;
}
errorHandlerRegistry.add(
    "supersededErrorHandler",
    /** @type {any} */ (supersededErrorHandler),
    { sequence: -1 },
);

/**
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @param {Error} originalError
 * @returns {boolean}
 */
export function rpcErrorHandler(env, error, originalError) {
    if (!(error instanceof UncaughtPromiseError)) {
        return false;
    }
    if (originalError instanceof RPCError) {
        error.unhandledRejectionEvent.preventDefault();
        const exceptionName = originalError.exceptionName;
        let ErrorComponent = /** @type {any} */ (originalError).Component;
        if (!ErrorComponent && exceptionName) {
            if (errorNotificationRegistry.contains(exceptionName)) {
                const notif = errorNotificationRegistry.get(exceptionName);
                env.services.notification.add(
                    notif.message || originalError.data.message,
                    notif,
                );
                return true;
            }
            if (errorDialogRegistry.contains(exceptionName)) {
                ErrorComponent = errorDialogRegistry.get(exceptionName);
            }
        }
        if (!ErrorComponent && originalError.data?.context) {
            const exceptionClass = /** @type {string} */ (
                originalError.data.context.exception_class
            );
            if (errorDialogRegistry.contains(exceptionClass)) {
                ErrorComponent = errorDialogRegistry.get(exceptionClass);
            }
        }

        env.services.dialog.add(ErrorComponent || RPCErrorDialog, {
            traceback: error.traceback,
            message: originalError.message,
            name: originalError.name,
            exceptionName: originalError.exceptionName,
            data: originalError.data,
            subType: originalError.subType,
            code: originalError.code,
            type: originalError.type,
            serverHost: /** @type {any} */ (error).event?.target?.location?.host,
            model: originalError.model,
        });
        return true;
    }
    return false;
}

errorHandlerRegistry.add("rpcErrorHandler", /** @type {any} */ (rpcErrorHandler), {
    sequence: 97,
});

/**
 * @typedef {{
 *   notifRemove: (() => void) | null,
 *   sessionExpiredOpen: boolean,
 *   retryTimer: any,
 *   destroyed: boolean,
 * }} ConnectionRecoveryState
 * @type {WeakMap<OdooEnv, ConnectionRecoveryState>}
 */
const connectionRecoveryByEnv = new WeakMap();

/**
 * @param {OdooEnv} env
 * @returns {ConnectionRecoveryState}
 */
function connectionRecoveryState(env) {
    let state = connectionRecoveryByEnv.get(env);
    if (!state) {
        state = {
            notifRemove: null,
            sessionExpiredOpen: false,
            retryTimer: null,
            destroyed: false,
        };
        connectionRecoveryByEnv.set(env, state);
    }
    return state;
}

/**
 * Tombstone rather than eviction: deleting the entry lets the next handler
 * call allocate a fresh `destroyed: false` state and re-arm the poll against
 * an env nobody is showing any more.
 *
 * @param {OdooEnv} env
 */
function connectionRecoveryDestroyed(env) {
    return connectionRecoveryByEnv.get(env)?.destroyed === true;
}

/**
 * @param {OdooEnv} env
 */
export function _resetConnectionRecovery(env) {
    connectionRecoveryByEnv.delete(env);
}

export const connectionRecoveryService = {
    /** @param {OdooEnv} env */
    start(env) {
        return {
            destroy() {
                const state = connectionRecoveryState(env);
                state.destroyed = true;
                if (state.retryTimer !== null) {
                    browser.clearTimeout(state.retryTimer);
                    state.retryTimer = null;
                }
                state.notifRemove = null;
            },
        };
    },
};

registry.category("services").add("connection_recovery", connectionRecoveryService);

/**
 * The two InvalidResponseError outcomes, split out of `lostConnectionHandler`.
 * A 200 is a session-expired redirect (the request got a login page) -> the
 * session-expired dialog, deduped via `state.sessionExpiredOpen`; any other
 * status is a malformed response -> a network-error dialog.
 *
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @param {InvalidResponseError} originalError
 * @param {any} state
 * @returns {boolean} always true -- the error is handled here
 */
function handleInvalidResponse(env, error, originalError, state) {
    if (originalError.status === 200) {
        if (state.sessionExpiredOpen) {
            return true;
        }
        state.sessionExpiredOpen = true;
        env.services.dialog.add(
            SessionExpiredDialog,
            {},
            {
                onClose: () => {
                    state.sessionExpiredOpen = false;
                },
            },
        );
        return true;
    }
    env.services.dialog.add(NetworkErrorDialog, {
        traceback: error.traceback,
        message: originalError.message,
        name: originalError.name,
        serverHost: /** @type {any} */ (error).event?.target?.location?.host,
    });
    return true;
}

/**
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @param {Error} originalError
 * @returns {boolean}
 */
export function lostConnectionHandler(env, error, originalError) {
    if (!(error instanceof UncaughtPromiseError)) {
        return false;
    }
    // InvalidResponseError is no longer a ConnectionLostError, but this handler
    // still owns it: the status-200 case below is the session-expired redirect.
    if (
        !(originalError instanceof ConnectionLostError) &&
        !(originalError instanceof InvalidResponseError)
    ) {
        return false;
    }
    if (connectionRecoveryDestroyed(env)) {
        error.unhandledRejectionEvent.preventDefault();
        return true;
    }
    const state = connectionRecoveryState(env);
    error.unhandledRejectionEvent.preventDefault();
    if (originalError instanceof InvalidResponseError) {
        return handleInvalidResponse(env, error, originalError, state);
    }
    if (state.notifRemove) {
        return true;
    }
    state.notifRemove = env.services.notification.add(
        _t("Connection lost. Trying to reconnect..."),
        { sticky: true },
    );
    let delay = 2000;
    state.retryTimer = browser.setTimeout(function checkConnection() {
        state.retryTimer = null;
        if (state.destroyed) {
            return;
        }
        rpc("/web/webclient/version_info", {}, { silent: true })
            .then(() => {
                if (state.destroyed) {
                    return;
                }
                if (state.notifRemove) {
                    state.notifRemove();
                    state.notifRemove = null;
                }
                env.services.notification.add(
                    _t("Connection restored. You are back online."),
                    {
                        type: "info",
                    },
                );
            })
            .catch(() => {
                if (state.destroyed) {
                    return;
                }
                delay = Math.min(delay * 1.5 + 500 * Math.random(), 60_000);
                state.retryTimer = browser.setTimeout(checkConnection, delay);
            });
    }, delay);
    return true;
}
errorHandlerRegistry.add(
    "lostConnectionHandler",
    /** @type {any} */ (lostConnectionHandler),
    {
        sequence: 98,
    },
);

/**
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @param {Error} originalError
 * @returns {boolean}
 */
export function requestEntityTooLargeHandler(env, error, originalError) {
    if (!(error instanceof UncaughtPromiseError)) {
        return false;
    }
    if (originalError instanceof RequestEntityTooLargeError) {
        error.unhandledRejectionEvent.preventDefault();
        env.services.dialog.add(RequestEntityTooLargeErrorDialog);
        return true;
    }
    return false;
}
errorHandlerRegistry.add(
    "requestEntityTooLargeHandler",
    /** @type {any} */ (requestEntityTooLargeHandler),
    {
        sequence: 99,
    },
);

const defaultDialogs = new Map([
    [UncaughtClientError, ClientErrorDialog],
    [UncaughtPromiseError, ClientErrorDialog],
    [ThirdPartyScriptError, NetworkErrorDialog],
]);

/**
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @returns {boolean}
 */
export function defaultHandler(env, error) {
    const DialogComponent =
        defaultDialogs.get(/** @type {any} */ (error.constructor)) || ErrorDialog;
    if (!env.services.dialog) {
        console.error(
            "Uncaught error before dialog service started:",
            error.name,
            error.message,
            error.traceback,
        );
        return true;
    }
    env.services.dialog.add(DialogComponent, {
        traceback: error.traceback,
        message: error.message,
        name: error.name,
        serverHost: /** @type {any} */ (error).event?.target?.location?.host,
    });
    return true;
}
errorHandlerRegistry.add("defaultHandler", /** @type {any} */ (defaultHandler), {
    sequence: 100,
});

errorHandlerRegistry.addValidation((v) => typeof v === "function");
