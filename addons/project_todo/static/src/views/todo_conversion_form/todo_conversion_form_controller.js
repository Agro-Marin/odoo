/** @odoo-module native */
import { onMounted } from "@odoo/owl";
import { FormController } from "@web/views/form";

export class TodoConversionFormController extends FormController {
    /**
     * Focus the first field of the conversion dialog.
     *
     * The renderer's own autofocus only runs for new records, and this dialog
     * edits the existing to-do, so it has to be done here. Scoped to this
     * controller's own root: a document-wide lookup would resolve against the
     * view sitting behind the dialog.
     *
     * @override
     * @private
     */
    setup() {
        super.setup();
        onMounted(() => {
            this.rootRef.el?.querySelector(".o_content .o_field_widget input")?.focus();
        });
    }
}
