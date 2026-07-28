// @ts-check
/** @odoo-module native */

/** @module @web/components/errors/error_handlers - Registry-based error handlers that route exceptions to appropriate dialogs or notifications */

/**
 * @typedef {import("../../env").OdooEnv} OdooEnv
 * @typedef {import("@web/core/errors/uncaught_errors").UncaughtError} UncaughtError
 */
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import {
    ConnectionLostError,
    InvalidResponseError,
    RequestEntityTooLargeError,
    rpc,
    RPCError,
} from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { SupersededError } from "@web/core/utils/concurrency";
import {
    ThirdPartyScriptError,
    UncaughtClientError,
    UncaughtPromiseError,
} from "@web/services/error_service";

import {
    ClientErrorDialog,
    ErrorDialog,
    NetworkErrorDialog,
    RequestEntityTooLargeErrorDialog,
    RPCErrorDialog,
    SessionExpiredDialog,
} from "./error_dialogs.js";

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
 * Swallow {@link SupersededError} silently: it is a control-flow signal (a
 * doAction/navigation superseded by a newer one), not a real failure. The
 * action service's KeepLast rejects superseded awaiters with it so their
 * ``finally`` runs and their ``await`` throws instead of hanging forever;
 * without this handler the resulting unhandled rejection would raise an error
 * dialog and log a traceback. Runs first (lowest sequence) so no later handler
 * ever sees it -- in particular it must precede the portal/public
 * ``swallowAllVisitorErrors`` handler (sequence 0), which swallows the error
 * WITHOUT ``preventDefault``: were it to win, ``shouldLogError()`` would still
 * console.error this control-flow signal's traceback for visitor users.
 *
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @param {Error} originalError
 * @returns {boolean} true (handled) when the error is a SupersededError
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
            const exceptionClass = originalError.data.context.exception_class;
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
}

errorHandlerRegistry.add("rpcErrorHandler", /** @type {any} */ (rpcErrorHandler), {
    sequence: 97,
});

let connectionLostNotifRemove = null;
let sessionExpiredDialogOpen = false;
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
    if (originalError instanceof ConnectionLostError) {
        error.unhandledRejectionEvent.preventDefault();
        if (originalError instanceof InvalidResponseError) {
            if (originalError.status === 200) {
                if (sessionExpiredDialogOpen) {
                    return true;
                }
                sessionExpiredDialogOpen = true;
                env.services.dialog.add(
                    SessionExpiredDialog,
                    {},
                    {
                        onClose: () => {
                            sessionExpiredDialogOpen = false;
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
        if (connectionLostNotifRemove) {
            return true;
        }
        connectionLostNotifRemove = env.services.notification.add(
            _t("Connection lost. Trying to reconnect..."),
            { sticky: true },
        );
        let delay = 2000;
        browser.setTimeout(function checkConnection() {
            rpc("/web/webclient/version_info", {}, { silent: true })
                .then(() => {
                    if (connectionLostNotifRemove) {
                        connectionLostNotifRemove();
                        connectionLostNotifRemove = null;
                    }
                    env.services.notification.add(
                        _t("Connection restored. You are back online."),
                        {
                            type: "info",
                        },
                    );
                })
                .catch(() => {
                    delay = Math.min(delay * 1.5 + 500 * Math.random(), 60_000);
                    browser.setTimeout(checkConnection, delay);
                });
        }, delay);
        return true;
    }
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
        // Without this the error service still sees a non-defaultPrevented
        // event and console.errors the traceback for what is a handled,
        // user-facing condition (see `shouldLogError` in error_service).
        error.unhandledRejectionEvent.preventDefault();
        env.services.dialog.add(RequestEntityTooLargeErrorDialog);
        return true;
    }
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
 * Handles errors based on the general error categories emitted by the error
 * service; the original error is not inspected here.
 *
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
