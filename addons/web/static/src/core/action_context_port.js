// @ts-check
/** @odoo-module native */

import { CallbackRecorder } from "@web/core/action_hook";

/**
 * @typedef {"__beforeLeave__" | "__getGlobalState__" | "__getLocalState__"
 * | "__getContext__" | "__getOrderBy__"} ActionContextSlot
 */

/** @type {readonly Function[]} */
const NO_CALLBACKS = Object.freeze([]);

class EmptyCallbackRecorder extends CallbackRecorder {
    /**
     * @returns {Function[]}
     */
    get callbacks() {
        return /** @type {Function[]} */ (NO_CALLBACKS);
    }
    /**
     * @param {any} _owner
     * @param {Function} _callback
     * @returns {never}
     */
    add(_owner, _callback) {
        throw new Error(
            "Cannot record a callback on the empty action-context recorder: " +
                "this env carries no recorder for that slot. Install one on the " +
                "env (see useSetupAction) before recording.",
        );
    }
    /**
     * @param {any} _owner
     */
    remove(_owner) {}
}

const EMPTY_RECORDER = Object.freeze(new EmptyCallbackRecorder());

/**
 * @param {Record<string, any>} env
 * @param {ActionContextSlot} slot
 * @returns {CallbackRecorder}
 */
export function actionContextRecorder(env, slot) {
    return env?.[slot] ?? EMPTY_RECORDER;
}

/**
 * @param {Record<string, any>} env
 * @param {ActionContextSlot} slot
 * @returns {Function[]}
 */
export function actionContextCallbacks(env, slot) {
    return actionContextRecorder(env, slot).callbacks;
}
