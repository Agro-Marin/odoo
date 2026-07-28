// @ts-check
/** @odoo-module native */

/** @module @web/webclient/errors/visitor_error_handler - Error handler that swallows all tracebacks for non-internal (portal/public) users */

import { RPCError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/services/user";
import { session } from "@web/session";

/**
 * Swallow errors for non-internal users (except in debug/test mode).
 *
 * What is being hidden is a traceback: a client-side crash a visitor can do
 * nothing with. A server exception the `error_notifications` registry knows
 * about is the opposite of that — a translated, deliberate message addressed to
 * whoever made the request, which is exactly what a public page's "this field
 * is invalid" comes back as. Swallowing those left a visitor filling a website
 * form with a submit that silently did nothing, so they pass through to
 * `rpcErrorHandler`, which renders them as a notification rather than a dialog.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {Error} error - The wrapped error
 * @param {Error} originalError - The original unwrapped error
 * @returns {true | undefined} `true` to swallow the error, `undefined` to pass through
 */
export function swallowAllVisitorErrors(env, error, originalError) {
    if (user.isInternalUser || env.debug || session.test_mode) {
        return;
    }
    if (
        originalError instanceof RPCError &&
        registry
            .category("error_notifications")
            .contains(/** @type {string} */ (originalError.exceptionName))
    ) {
        return;
    }
    return true;
}

if (user.isInternalUser === undefined) {
    if (session.is_frontend) {
        console.warn(
            "isInternalUser information is required for this handler to work. It must be available in the page.",
        );
    }
} else {
    registry
        .category("error_handlers")
        .add("swallowAllVisitorErrors", swallowAllVisitorErrors, {
            sequence: 0,
        });
}
