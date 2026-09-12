// @ts-check
/** @odoo-module native */

import { useComponent, useExternalListener } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/ui/popover/popover_hook";

/**
 * @param {typeof import("@odoo/owl").Component} component
 * @returns {{ close: Function, open: Function, isOpen: boolean }}
 */
export function useCalendarPopover(component) {
    const owner = useComponent();
    let popoverClasses = "";
    /** @type {any} */
    const popoverOptions = {
        extendedFlipping: true,
        position: "right",
        onClose: cleanup,
    };
    Object.defineProperty(popoverOptions, "class", {
        get: () => popoverClasses,
    });
    const popover = usePopover(component, popoverOptions);
    const dialog = useService("dialog");
    let removeDialog = null;
    let fcPopover;
    useExternalListener(
        window,
        "mousedown",
        (ev) => {
            if (fcPopover) {
                ev.stopPropagation();
            }
        },
        { capture: true },
    );
    function cleanup() {
        fcPopover = null;
        removeDialog = null;
    }
    function close() {
        removeDialog?.();
        popover.close();
        cleanup();
    }
    return {
        close,
        get isOpen() {
            return owner.env.isSmall ? Boolean(removeDialog) : popover.isOpen;
        },
        open(target, props, classToUse) {
            const targetFcPopover = target.closest(".fc-popover");
            if (owner.env.isSmall) {
                close();
                removeDialog = dialog.add(component, props, {
                    onClose: cleanup,
                });
            } else {
                popoverClasses = classToUse;
                popover.open(target, props);
            }
            fcPopover = targetFcPopover;
        },
    };
}
