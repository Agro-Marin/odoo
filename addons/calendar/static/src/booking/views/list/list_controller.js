/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list";
import { AppointmentTemplatePickerDialog } from "@calendar/booking/components/appointment_template_picker_dialog/appointment_template_picker_dialog";

export class AppointmentTypeListController extends ListController {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
    }
    /**
     * @override
     */
    async createRecord() {
        this.dialog.add(AppointmentTemplatePickerDialog, {});
    }
}
