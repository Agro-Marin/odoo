// @ts-check
/** @odoo-module native */

import { onWillUnmount, reactive, useEffect, useExternalListener } from "@odoo/owl";
import { useThrottleForAnimation } from "@web/core/utils/timing";

import { makeNativeDraggableHook } from "./draggable_hook_builder.js";

export const OWL_SETUP_HOOKS = Object.freeze({
    addListener: useExternalListener,
    setup: useEffect,
    teardown: onWillUnmount,
    throttle: useThrottleForAnimation,
    wrapState: reactive,
});

/**
 * @type {typeof makeNativeDraggableHook}
 */
export function makeDraggableHook(params) {
    return makeNativeDraggableHook(
        /** @type {any} */ ({ ...params, setupHooks: OWL_SETUP_HOOKS }),
    );
}
