// @ts-check
/** @odoo-module native */

import { onWillUnmount, reactive, useEffect, useExternalListener } from "@odoo/owl";
import { useThrottleForAnimation } from "@web/core/utils/timing";

import { makeNativeDraggableHook } from "./draggable_hook_builder.js";

/**
 * The OWL adapter the framework-agnostic dnd builders are parameterised on:
 * each of the five hooks they need, bound to its OWL equivalent.
 *
 * Shared rather than written out at each entry point. The two of them --
 * `makeDraggableHook` here and `sortable_owl`'s `useSortable` -- carried the
 * same five bindings verbatim, so a hook added to the contract could be
 * wired on one side and silently missing on the other. Frozen because
 * `draggable_hook_builder` only ever reads off it.
 */
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
