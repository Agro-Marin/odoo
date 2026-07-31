// @ts-check
/** @odoo-module native */

import { AppEvent } from "@web/core/events";

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {{ forceLeave?: boolean }} [options]
 * @returns {Promise<boolean>}
 */
export async function clearUncommittedChanges(
    env,
    { forceLeave } = /** @type {any} */ ({}),
) {
    /** @type {Array<(param0: { forceLeave: any }) => any>} */
    const callbacks = [];
    env.bus.trigger(AppEvent.CLEAR_UNCOMMITTED_CHANGES, callbacks);
    const res = await Promise.all(callbacks.map((fn) => fn({ forceLeave })));
    return !res.includes(false);
}
