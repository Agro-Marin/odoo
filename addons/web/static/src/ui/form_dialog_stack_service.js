// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

/**
 * @typedef {{
 * push: () => void,
 * pop: () => void,
 * readonly count: number,
 * readonly isEmpty: boolean,
 * }} FormDialogStackService
 */
const formDialogStackService = {
    /**
     * @returns {FormDialogStackService}
     */
    start() {
        let count = 0;
        return {
            push() {
                count++;
            },
            pop() {
                if (count === 0) {
                    if (odoo.debug) {
                        console.warn(
                            "[form_dialog_stack] pop() called with no open form-in-dialog (unbalanced push/pop)",
                        );
                    }
                    return;
                }
                count--;
            },
            get count() {
                return count;
            },
            get isEmpty() {
                return count === 0;
            },
        };
    },
};

registry.category("services").add("form_dialog_stack", formDialogStackService);
