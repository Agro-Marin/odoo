// @ts-check
/** @odoo-module native */

/** @module @web/ui/popover/popover_hook */

import { onWillUnmount, status, useComponent } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
/**
 * @import { PopoverServiceAddFunction, PopoverServiceAddOptions } from "@web/ui/popover/popover_service"
 */

/**
 * @typedef PopoverHookReturnType
 * @property {(target: string | HTMLElement, props: object) => void} open
 * @property {(removeParams?: any) => void} close
 * @property {boolean} isOpen
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
    function close(/** @type {any} */ removeParams = undefined) {
        removeFn?.(removeParams);
    }
    return {
        open(target, props) {
            close();
            // Object.create, not a spread: callers define options as lazy
            // getters (Dropdown's `position` and `class` read live state), and
            // a spread would snapshot them here instead.
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
 * @param {import("@odoo/owl").ComponentConstructor} component
 * @param {PopoverServiceAddOptions} [options]
 * @returns {PopoverHookReturnType}
 */
export function usePopover(component, options = {}) {
    const popoverService = useService("popover");
    const owner = useComponent();

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
    onWillUnmount(() => popover.close());
    return popover;
}
