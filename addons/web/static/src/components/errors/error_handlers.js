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
} from "./error_dialogs.js";

const errorHandlerRegistry = registry.category("error_handlers");
const errorDialogRegistry = registry.category("error_dialogs");
const errorNotificationRegistry = registry.category("error_notifications");

// Error dialogs are OWL Component classes; the error service mounts the
// matching one for an exception name (see `RPCErrorDialog` and friends).
errorDialogRegistry.addValidation((entry) => typeof entry === "function");

// Error notifications are toast configs: `title` / `message` / `type` /
// `sticky` / `buttons` are forwarded to the notification service. All fields
// are optional because callers compose missing pieces from the error itself.
errorNotificationRegistry.addValidation({
    title: { type: [String, Object], optional: true },
    message: { type: [String, Object], optional: true },
    type: { type: String, optional: true },
    sticky: { type: Boolean, optional: true },
    buttons: { type: Array, optional: true },
    "*": true,
});

// -----------------------------------------------------------------------------
// Superseded tasks (KeepLast rejectSuperseded mode)
// -----------------------------------------------------------------------------

/**
 * Swallow {@link SupersededError} silently: it is a control-flow signal (a
 * doAction/navigation superseded by a newer one), not a real failure. The
 * action service's KeepLast rejects superseded awaiters with it so their
 * ``finally`` runs and their ``await`` throws instead of hanging forever;
 * without this handler the resulting unhandled rejection would raise an error
 * dialog and log a traceback. Runs first (low sequence) so no later handler
 * ever sees it.
 *
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @param {Error} originalError
 * @returns {boolean} true (handled) when the error is a SupersededError
 */
export function supersededErrorHandler(env, error, originalError) {
    if (originalError instanceof SupersededError || error instanceof SupersededError) {
        // Prevent the browser's default report + the error service's traceback
        // log (shouldLogError() short-circuits once the event is defaultPrevented).
        /** @type {any} */ (error).event?.preventDefault?.();
        return true;
    }
    return false;
}
errorHandlerRegistry.add(
    "supersededErrorHandler",
    /** @type {any} */ (supersededErrorHandler),
    { sequence: 1 },
);

// -----------------------------------------------------------------------------
// RPC errors
// -----------------------------------------------------------------------------

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
        // A server-side error can carry an exceptionName used as a registry
        // key to pick a dialog component (lets a backend dev map an error to
        // a specific component). Client-side errors set `component` directly.
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

// -----------------------------------------------------------------------------
// Lost connection errors
// -----------------------------------------------------------------------------

let connectionLostNotifRemove = null;
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
        // Like rpcErrorHandler: a handler that fully owns an error (sticky
        // notification + reconnect polling) MUST preventDefault the
        // unhandled-rejection event. Otherwise error_service's
        // shouldLogError() (which only checks event.defaultPrevented) still
        // logs a redundant console.error — duplicating the toast and failing
        // browser-tour HttpCase tests that treat any console.error as fatal
        // (see test_main_flows.TestUi.test_01_main_flow_tour racing the
        // first /mail/data init_messaging RPC on cold boot).
        error.unhandledRejectionEvent.preventDefault();
        if (connectionLostNotifRemove) {
            // notification already displayed (can occur if there were several
            // concurrent rpcs when the connection was lost)
            return true;
        }
        connectionLostNotifRemove = env.services.notification.add(
            _t("Connection lost. Trying to reconnect..."),
            { sticky: true },
        );
        let delay = 2000;
        browser.setTimeout(function checkConnection() {
            // Silent: the probe fires every 2s→60s during an outage — a
            // non-silent RPC would flash the loading indicator and feed the
            // slow-RPC toast on top of the "Connection lost" notification.
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
                    // exponential backoff, with some jitter, capped so the
                    // retry interval can't grow without bound on a long outage.
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

// -----------------------------------------------------------------------------
// Request entity too large errors
// -----------------------------------------------------------------------------

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

// -----------------------------------------------------------------------------
// Default handler
// -----------------------------------------------------------------------------

const defaultDialogs = new Map([
    [UncaughtClientError, ClientErrorDialog],
    [UncaughtPromiseError, ClientErrorDialog],
    [ThirdPartyScriptError, NetworkErrorDialog],
]);

/**
 * Handles the errors based on the very general error categories emitted by the
 * error service. Notice how we do not look at the original error at all.
 *
 * @param {OdooEnv} env
 * @param {UncaughtError} error
 * @returns {boolean}
 */
export function defaultHandler(env, error) {
    const DialogComponent =
        defaultDialogs.get(/** @type {any} */ (error.constructor)) || ErrorDialog;
    // ``errorService`` starts in the first wave (no deps) so it can capture
    // errors during the boot of any other service.  The dialog service starts
    // later (depends on ``overlay``).  If an error fires in that window we
    // would crash with "Cannot read properties of undefined (reading 'add')",
    // turning a single startup glitch into a meta-error that masks the real
    // failure.  Fall back to ``console.error`` until dialog is available.
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

// Error handlers are bare functions invoked as ``handler(env, uncaughtError,
// originalError)`` by ``error_service.js`` at line 78. A non-function entry
// would surface there as ``TypeError: handler is not a function`` AND swallow
// the original error along the way (the catch around the call returns rather
// than rethrowing, so a handler bug masks the underlying error). The
// predicate catches the bad registration at definition time with a precise
// message. Throws in debug, warns in production (see ``core/registry.js
// validateSchema``).
errorHandlerRegistry.addValidation((v) => typeof v === "function");
