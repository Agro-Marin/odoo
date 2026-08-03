/** @odoo-module native */
import { _t } from "@web/core/translation";
import { ConfirmationDialog } from "@web/ui/dialog";
import { registry } from "@web/core/registry";
import { FormController, formView } from "@web/views/form";

export class FleetFormController extends FormController {
    /**
     * @override
     **/
    getStaticActionMenuItems() {
        const menuItems = super.getStaticActionMenuItems();
        menuItems.archive.callback = () => {
            const dialogProps = {
                body: _t(
                    "Every service and contract of this vehicle will be considered as archived. Are you sure that you want to archive this record?"
                ),
                confirm: () => this.model.root.archive(),
                cancel: () => {},
            };
            this.dialogService.add(ConfirmationDialog, dialogProps);
        };
        return menuItems;
    }
}

export const fleetFormView = {
    ...formView,
    Controller: FleetFormController,
};

registry.category("views").add("fleet_form", fleetFormView);
