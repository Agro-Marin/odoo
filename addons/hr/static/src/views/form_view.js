/** @odoo-module native */
import { useArchiveEmployee } from "@hr/views/archive_employee_hook";
import { registry } from "@web/core/registry";
import { FormController,formView } from "@web/views/form";

export class EmployeeFormController extends FormController {
    setup() {
        super.setup();
        this.archiveEmployee = useArchiveEmployee();
    }

    getStaticActionMenuItems() {
        const menuItems = super.getStaticActionMenuItems();
        menuItems.archive.callback = this.archiveEmployee.bind(this, [this.model.root.resId]);
        return menuItems;
    }
}

registry.category("views").add("hr_employee_form", {
    ...formView,
    Controller: EmployeeFormController,
});
