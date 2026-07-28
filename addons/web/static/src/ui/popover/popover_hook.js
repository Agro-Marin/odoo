// @ts-check
/** @odoo-module native */

/** @module @web/ui/popover/popover_hook - usePopover hook for open/close lifecycle management within OWL components */

import { onWillUnmount, status, useComponent } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/** @import { PopoverServiceAddFunction, PopoverServiceAddOptions } from "@web/ui/popover/popover_service" */

/**
 * @typedef PopoverHookReturnType
 * @property {(target: string | HTMLElement, props: object) => void} open
 *  - Signals the manager to open the configured popover
 *    component on the target, with the given props.
 * @property {(removeParams?: any) => void} close
 *  - Signals the manager to remove the popover, optionally with a reason
 *    that reaches `options.onClose`.
 * @property {boolean} isOpen
 *  - Whether the popover is currently open.
 */

/**
 * @param {PopoverServiceAddFunction} addFn
 * @param {import("@odoo/owl").ComponentConstructor} component
 * @param {PopoverServiceAddOptions} options
 * @returns {PopoverHookReturnType}
 */
export function makePopover(addFn, component, options) {
    /** @type {((removeParams?: any) => void) | null} */
    let removeFn = null;
    /**
     * Forwards its argument the whole way down. The presenter binds the hosted
     * component's `close` to pass a reason on; a thunk here would have dropped
     * it again one layer up, which is where nearly every caller sits.
     */
    function close(/** @type {any} */ removeParams) {
        removeFn?.(removeParams);
    }
    return {
        open(target, props) {
            close();
            const newOptions = Object.create(options);
            newOptions.onClose = (/** @type {any} */ removeParams) => {
                removeFn = null;
                options.onClose?.(removeParams);
            };
            removeFn = addFn(/** @type {any} */ (target), component, props, newOptions);
        },
        close,
        get isOpen() {
            return Boolean(removeFn);
        },
    };
}

/**
 * Manages a component to be used as a popover.
 *
 * @param {import("@odoo/owl").ComponentConstructor} component
 * @param {PopoverServiceAddOptions} [options]
 * @returns {PopoverHookReturnType}
 */
export function usePopover(component, options = {}) {
    const popoverService = useService("popover");
    const owner = useComponent();

    /**
     * Resolved per `open()`, not once in `setup()`: `useBottomSheet` is
     * normally derived from a live media query (`Dropdown.isBottomSheet`), and
     * a breakpoint change does not remount its component — freezing the choice
     * left a rotated tablet opening desktop popovers for the rest of the
     * session.
     */
    const { useBottomSheet } = /** @type {any} */ (options);
    const wantsBottomSheet =
        typeof useBottomSheet === "function"
            ? useBottomSheet
            : () => Boolean(useBottomSheet);
    const add = (/** @type {any[]} */ ...args) => {
        const service =
            (wantsBottomSheet() && owner.env.services.bottom_sheet) || popoverService;
        return service.add(...args);
    };

    const newOptions = Object.create(options);
    newOptions.onClose = (/** @type {any} */ removeParams) => {
        if (status(owner) !== "destroyed") {
            options.onClose?.(removeParams);
        }
    };
    const popover = makePopover(add, component, newOptions);
    // Wrapped: an unmount is not a close reason, and handing Owl's hook the
    // bare function would make whatever it passes one.
    onWillUnmount(() => popover.close());
    return popover;
}
