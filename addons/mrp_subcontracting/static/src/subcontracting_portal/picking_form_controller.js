/** @odoo-module native */
import { registry } from "@web/core/registry";
import { FormController, formView } from "@web/views/form";
import { useDialogContext } from "@web/core/dialog_context_hooks";

class PickingFormController extends FormController {
    static template = "mrp_subcontracting.PickingFormController";

    setup() {
        super.setup();
        this.dialogContext = useDialogContext();
    }
}

const PickingFormView = {
    ...formView,
    Controller: PickingFormController,
};

registry
    .category("views")
    .add("subcontracting_portal_picking_form_view", PickingFormView);
