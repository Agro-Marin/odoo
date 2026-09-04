// @ts-check
/** @odoo-module native */
import { useState } from "@odoo/owl";
import { FormController } from "@web/views/form";

export class FormControllerWithHTMLExpander extends FormController {
    static template = "web.FormViewWithHtmlExpander";

    /** @type {{ reload: boolean }} */
    htmlExpanderState;

    setup() {
        super.setup();
        this.htmlExpanderState = useState({ reload: true });
        const oldOnNotebookPageChange = this.onNotebookPageChange;
        /** @param {string} notebookId @param {string} page */
        this.onNotebookPageChange = (notebookId, page) => {
            oldOnNotebookPageChange(notebookId, page);
            if (page && !this.htmlExpanderState.reload) {
                this.htmlExpanderState.reload = true;
            }
        };
    }

    get modelParams() {
        const modelParams = super.modelParams;

        const lifecycle = /** @type {Record<string, any>} */ (
            modelParams.hooks.lifecycle
        );
        const onRootLoaded = lifecycle.onRootLoaded;
        lifecycle.onRootLoaded = async () => {
            if (onRootLoaded) {
                onRootLoaded();
            }
            this.htmlExpanderState.reload = true;
        };
        return modelParams;
    }

    notifyHTMLFieldExpanded() {
        this.htmlExpanderState.reload = false;
    }

    /** @param {any} record @param {any} changes */
    async onRecordSaved(record, changes) {
        super.onRecordSaved(record, changes);
        this.htmlExpanderState.reload = true;
    }
}
