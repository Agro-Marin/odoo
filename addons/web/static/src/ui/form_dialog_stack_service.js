// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

class FormDialogStackService {
    constructor() {
        this.depth = 0;
    }

    push() {
        this.depth++;
    }

    pop() {
        if (this.depth === 0) {
            if (odoo.debug) {
                console.warn(
                    "[form_dialog_stack] pop() called with no open form-in-dialog (unbalanced push/pop)",
                );
            }
            return;
        }
        this.depth--;
    }

    get count() {
        return this.depth;
    }

    get isEmpty() {
        return this.depth === 0;
    }
}

const formDialogStackService = {
    /**
     * @returns {FormDialogStackService}
     */
    start() {
        return new FormDialogStackService();
    },
};

registry.category("services").add("form_dialog_stack", formDialogStackService);
