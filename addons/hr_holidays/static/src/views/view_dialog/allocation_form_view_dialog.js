/** @odoo-module native */
import { FormViewDialog } from "@web/views/view_dialogs";

export class AllocationFormViewDialog extends FormViewDialog {
    setup() {
        super.setup();
        Object.assign(this.viewProps, {
            buttonTemplate: 'hr_holidays.AllocationFormViewDialog.buttons',
        });
    }
};
