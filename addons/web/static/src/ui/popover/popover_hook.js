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
    /** @type {((removeParams?: any) => Promise<void>) | null} */
    let removeFn = null;
    function close(/** @type {any} */ removeParams = undefined) {
        removeFn?.(removeParams);
    }
    return {
        open(target, props) {
            close();
            // Object.create, not a spread, so that overriding onClose below
            // shadows the caller's option instead of mutating the object they
            // handed over -- the same options are reused for every open.
            //
            // It does NOT make lazy option getters live: the presenter reads
            // each one once, when the overlay is added, and hands the overlay a
            // plain snapshot. Options are the state at open time; anything that
            // has to follow the opener afterwards belongs in the hosted
            // component's props.
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
