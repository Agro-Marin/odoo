// @ts-check
/** @odoo-module native */

import { onWillUnmount, status, useComponent } from "@odoo/owl";
import { reportUncaught } from "@web/core/errors/error_utils";
import { useService } from "@web/core/utils/hooks";
/**
 * @import { PopoverServiceAddFunction, PopoverServiceAddOptions } from "@web/ui/popover/popover_service"
 */

/**
 * @typedef PopoverHookReturnType
 * @property {(target: string | HTMLElement, props: object) => void} open
 * @property {(removeParams?: any) => Promise<void> | undefined} close
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
        return removeFn?.(removeParams);
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
        // eslint-disable-next-line no-restricted-syntax
        const sheetService = owner.env.services.bottom_sheet;
        const service = (wantsBottomSheet() && sheetService) || popoverService;
        return service.add(...args);
    };

    const newOptions = Object.create(options);
    newOptions.onClose = (/** @type {any} */ removeParams) => {
        if (status(owner) !== "destroyed") {
            options.onClose?.(removeParams);
        }
    };
    const popover = makePopover(add, component, newOptions);
    // close() settles when the caller's onClose does. At unmount nobody is left
    // to await it, so a throwing onClose would surface as an unhandled rejection
    // Owl reports as an onWillUnmount error, naming the wrong culprit.
    onWillUnmount(() => popover.close()?.catch(reportUncaught));
    return popover;
}
