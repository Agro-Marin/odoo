/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { ListController, listView } from "@web/views/list";
import { FormViewDialog } from "@web/views/view_dialogs";

class AppointmentShareLinkListController extends ListController {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
    }

    async onClickCreate() {
        this.dialog.add(FormViewDialog, {
            resModel: "appointment.invite",
            size: "md",
            title: _t("Create a Share Link"),
            context: this.props.context?.active_ids
                ? { default_appointment_type_ids: this.props.context.active_ids }
                : {},
        });
    }

    async openRecord(record) {
        this.dialog.add(FormViewDialog, {
            resId: record.resId,
            resModel: "appointment.invite",
            size: "md",
            title: _t("Update a Share Link"),
        });
    }
}

registry.category("views").add("appointment_share_link_list", {
    ...listView,
    Controller: AppointmentShareLinkListController,
});
