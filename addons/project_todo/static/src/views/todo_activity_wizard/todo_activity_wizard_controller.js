/** @odoo-module native */
import { onMounted } from "@odoo/owl";
import { FormController } from "@web/views/form";

export class TodoActivityWizardController extends FormController {
    setup() {
        super.setup();
        onMounted(() => {
            const firstInput = document.querySelector('div.o_field_widget input');
            firstInput.focus();
        });
    }
}
