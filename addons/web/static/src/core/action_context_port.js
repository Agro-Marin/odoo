// @ts-check
/** @odoo-module native */

/** @module @web/core/action_context_port */

import { CallbackRecorder } from "@web/core/action_hook";

/**
 * The five `__*__` slots an action context publishes on `env`, read through one
 * place instead of off `env` by string key.
 *
 * **The problem this solves is that the slots have two "off" shapes.** A
 * consumer sees a `CallbackRecorder` when a producer installed one
 * (`webclient/actions/controller_component.js`,
 * `search/with_search/with_search.js`, `views/view_dialogs/form_view_dialog.js`),
 * `undefined` when none did, and `null` when something opted out explicitly —
 * `enterprise/web_studio`'s `studio_view.js` sets all five to `null`. Consumers
 * then disagree about which of those they handle: `core/action_hook.js` guards
 * every key, while `search/search_favorites_mixin.js` used to dereference
 * `env.__getContext__.callbacks` unguarded, so saving a favourite in a context
 * that had nulled the slots threw a `TypeError`.
 *
 * Normalising here collapses `undefined` and `null` into the same thing a
 * present-but-empty recorder already is: something with no callbacks. A reader
 * that only wants to run the callbacks therefore needs no guard at all, and
 * cannot tell "absent" from "disabled" — which is correct, because for that
 * question they mean the same thing.
 *
 * **This deliberately does not change registration.** `useSetupAction` keeps
 * its `if (__beforeLeave__ && …)` guards: there, absence is load-bearing —
 * registering into a null-object would silently accept a callback nobody will
 * ever call, which is the failure this port exists to make visible rather than
 * to spread. Reading is normalised; writing still asks whether there is
 * anywhere to write.
 *
 * @typedef {"__beforeLeave__" | "__getGlobalState__" | "__getLocalState__"
 *           | "__getContext__" | "__getOrderBy__"} ActionContextSlot
 */

/** Shared and frozen: a reader may iterate it but must never record into it. */
const EMPTY_RECORDER = Object.freeze(new CallbackRecorder());

/**
 * The recorder in `slot`, or an empty one when nothing installed it or a
 * producer opted out with `null`.
 *
 * @param {Record<string, any>} env
 * @param {ActionContextSlot} slot
 * @returns {CallbackRecorder}
 */
export function actionContextRecorder(env, slot) {
    return env?.[slot] ?? EMPTY_RECORDER;
}

/**
 * The callbacks registered in `slot`, or `[]`. The common case — a caller that
 * wants to invoke them and does not care whether anyone is listening.
 *
 * @param {Record<string, any>} env
 * @param {ActionContextSlot} slot
 * @returns {Function[]}
 */
export function actionContextCallbacks(env, slot) {
    return actionContextRecorder(env, slot).callbacks;
}
