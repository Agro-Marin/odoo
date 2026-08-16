/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { KanbanController } from "@web/views/kanban";
export class MailActivityMyKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.store = useService("mail.store");
    }

    async createRecord() {
        return this.store
            .scheduleActivity(
                this.props.resModel !== "mail.activity" ? this.props.resModel : false,
                false,
            )
            .then(async () => {
                await this.model.root.load();
            });
    }
}
