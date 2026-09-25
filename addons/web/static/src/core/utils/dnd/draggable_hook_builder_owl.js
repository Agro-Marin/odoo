// @ts-check
/** @odoo-module native */

import { onWillUnmount, reactive, useExternalListener } from "@odoo/owl";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { useThrottleForAnimation } from "@web/core/utils/timing";

import { makeNativeDraggableHook } from "./draggable_hook_builder.js";

export const OWL_SETUP_HOOKS = Object.freeze({
    addListener: useExternalListener,
    setup: useLayoutEffect,
    teardown: onWillUnmount,
    throttle: useThrottleForAnimation,
    wrapState: reactive,
});

/** @param {Omit<import("./draggable_hook_builder").DraggableBuilderParams, "setupHooks">} params */
export function makeDraggableHook(params) {
    return makeNativeDraggableHook({ ...params, setupHooks: OWL_SETUP_HOOKS });
}
