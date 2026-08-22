/** @odoo-module native */
import { useState } from "@odoo/owl";
import { FormController } from "@web/views/form";

export class FormControllerWithHTMLExpander extends FormController {
    static template = "resource.FormViewWithHtmlExpander";

    setup() {
        super.setup();
        this.htmlExpanderState = useState({ reload: true });
        const oldOnNotebookPageChange = this.onNotebookPageChange;
        this.onNotebookPageChange = (notebookId, page) => {
            oldOnNotebookPageChange(notebookId, page);
            if (page && !this.htmlExpanderState.reload) {
                this.htmlExpanderState.reload = true;
            }
        };
    }

    get modelParams() {
        const modelParams = super.modelParams;
        // `lifecycleHooks` is a getter on the MODEL (`relational_model.js:253`,
        // returning `this.hooks.lifecycle`); the params object this reads has
        // only `hooks.lifecycle`, so the shorter spelling is `undefined` here.
        const onRootLoaded = modelParams.hooks.lifecycle.onRootLoaded;
        modelParams.hooks.lifecycle.onRootLoaded = async () => {
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

    async onRecordSaved(record, changes) {
        super.onRecordSaved(record, changes);
        this.htmlExpanderState.reload = true;
    }
}
