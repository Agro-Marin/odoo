/** @odoo-module native */
import { onMounted } from "@odoo/owl";
import { FormController } from "@web/views/form";

export class TodoConversionFormController extends FormController {
    /**
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
