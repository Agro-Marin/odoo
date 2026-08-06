// @ts-check
/** @odoo-module native */

/** @module @web/webclient/errors/offline_fail_to_fetch_error_handler */

import { lostConnectionHandler } from "@web/components/errors/error_handlers";
import { reportUncaught } from "@web/core/errors/error_utils";
import { ConnectionLostError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
const errorHandlerRegistry = registry.category("error_handlers");

const fetchErrorMessages = [
    "Failed to fetch",
    "Load failed",
    "NetworkError when attempting to fetch resource.",
];

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {any} error
 * @param {Error} originalError
 * @returns {boolean}
 */
export function offlineFailToFetchErrorHandler(env, error, originalError) {
    if (
        originalError instanceof TypeError &&
        fetchErrorMessages.includes(originalError.message)
    ) {
        const connectionError = new ConnectionLostError(originalError.message, {
            cause: originalError,
        });
        if (lostConnectionHandler(env, error, connectionError)) {
            return true;
        }
        // Sync "error" events never reach `lostConnectionHandler` (it only
        // handles promise rejections): hand the failure to the async path,
        // and default-prevent the original event so an offline hiccup
        // handled here does not reach the js_error beacon.
        error.event?.preventDefault();
        reportUncaught(connectionError);
        return true;
    }
    return false;
}
errorHandlerRegistry.add(
    "offlineFailToFetchErrorHandler",
    offlineFailToFetchErrorHandler,
    {
        sequence: 96,
    },
);
