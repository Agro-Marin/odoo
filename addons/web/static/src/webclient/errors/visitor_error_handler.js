// @ts-check
/** @odoo-module native */

import { ConnectionLostError, RPCError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { session } from "@web/session";

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {Error} error
 * @param {Error} originalError
 * @returns {true | undefined}
 */
export function swallowAllVisitorErrors(env, error, originalError) {
    if (user.isInternalUser !== false || env.debug || session.test_mode) {
        return;
    }
    if (originalError instanceof ConnectionLostError) {
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

if (user.isInternalUser === undefined && session.is_frontend) {
    console.warn(
        "isInternalUser information is required for this handler to work. It must be available in the page.",
    );
}

registry
    .category("error_handlers")
    .add("swallowAllVisitorErrors", swallowAllVisitorErrors, {
        sequence: 0,
    });
