// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_clear_changes - Cross-controller "are you sure" prompt for uncommitted form edits before action transitions */

import { AppEvent } from "@web/core/events";

/**
 * Broadcast ``CLEAR-UNCOMMITTED-CHANGES`` on the env bus so every mounted
 * controller can opt to veto the upcoming action transition.  Subscribers
 * push callback functions into the shared ``callbacks`` array (see
 * ``controller_component.js`` `setup()`); the function awaits all of them
 * and returns ``true`` iff none returned ``false``.
 *
 * Lives in its own module so sibling action-layer modules
 * (``action_executors/act_window``, ``action_executors/client``) can import
 * it without creating a circular dependency on ``action_service.js``.
 * Importing from ``action_service.js`` worked semantically (function
 * declarations are hoisted), but the cycle made it harder to reason
 * about evaluation order under esbuild — extracting here removes the
 * question entirely.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {{ forceLeave?: boolean }} [options]
 * @returns {Promise<boolean>} ``true`` if every subscriber consented to
 *   the transition (or none answered).
 */
export async function clearUncommittedChanges(
    env,
    { forceLeave } = /** @type {any} */ ({}),
) {
    const callbacks = [];
    env.bus.trigger(AppEvent.CLEAR_UNCOMMITTED_CHANGES, callbacks);
    const res = await Promise.all(callbacks.map((fn) => fn({ forceLeave })));
    return !res.includes(false);
}
