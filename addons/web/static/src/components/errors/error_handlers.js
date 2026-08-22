// @ts-check
/** @odoo-module native */

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
import {
    ThirdPartyScriptError,
    UncaughtClientError,
    UncaughtPromiseError,
} from "@web/core/errors/error_service";
import {
    ConnectionLostError,
    InvalidResponseError,
    RequestEntityTooLargeError,
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
        error.unhandledRejectionEvent?.preventDefault();
        const exceptionName = originalError.exceptionName;
        let ErrorComponent = /** @type {any} */ (originalError).Component;
        if (!ErrorComponent && exceptionName) {
            if (errorNotificationRegistry.contains(exceptionName)) {
                const notif = errorNotificationRegistry.get(exceptionName);
                env.services.notification.add(
                    notif.message ||
                        originalError.data?.message ||
                        originalError.message,
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
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @param {InvalidResponseError} originalError
 * @param {any} recovery
 * @returns {boolean}
 */
function handleInvalidResponse(env, error, originalError, recovery) {
    if (originalError.status === 200) {
        recovery.openSessionExpired(() =>
            env.services.dialog.add(
                SessionExpiredDialog,
                {},
                { onClose: () => recovery.closeSessionExpired() },
            ),
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
    if (
        !(originalError instanceof ConnectionLostError) &&
        !(originalError instanceof InvalidResponseError)
    ) {
        return false;
    }
    const recovery = env.services.connection_recovery;
    error.unhandledRejectionEvent?.preventDefault();
    if (!recovery || recovery.isDestroyed) {
        return true;
    }
    if (originalError instanceof InvalidResponseError) {
        return handleInvalidResponse(env, error, originalError, recovery);
    }
    recovery.reportLost({
        lost: () =>
            env.services.notification.add(
                _t("Connection lost. Trying to reconnect..."),
                {
                    sticky: true,
                },
            ),
        restored: () =>
            env.services.notification.add(
                _t("Connection restored. You are back online."),
                {
                    type: "info",
                },
            ),
    });
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
function requestEntityTooLargeHandler(env, error, originalError) {
    if (!(error instanceof UncaughtPromiseError)) {
        return false;
    }
    if (originalError instanceof RequestEntityTooLargeError) {
        error.unhandledRejectionEvent?.preventDefault();
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
