/** @odoo-module native */
import { ListController } from "@web/views/list";
import { useService } from "@web/core/utils/hooks";

export class DataCleaningCommonListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notificationService = useService("notification");
    }

    /**
     * Open the form view of the record the row points at, not the proposal row itself.
     * @override
     */
    openRecord(record) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            views: [[false, "form"]],
            res_model: record.data.res_model_name,
            res_id: record.data.res_id,
            context: {
                create: false,
                edit: false,
            },
        });
    }

    onUnselectClick() {
        this.discardSelection();
    }
}
