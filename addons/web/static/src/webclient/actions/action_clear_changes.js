// @ts-check
/** @odoo-module native */

import { AppEvent } from "@web/core/events";

/**
 * Broadcast ``CLEAR-UNCOMMITTED-CHANGES`` on the env bus so every mounted
 * controller can veto the upcoming action transition. Subscribers push
 * callbacks into the shared ``callbacks`` array (see
 * ``controller_component.js`` `setup()`); resolves ``true`` iff none
 * returned ``false``.
 *
 * Extracted out of ``action_service.js`` so sibling action-layer modules
 * (``action_executors/act_window``, ``action_executors/client``) can import
 * it without a circular dependency — the cycle worked via hoisting, but
 * complicated reasoning about evaluation order under esbuild.
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
