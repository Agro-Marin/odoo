/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list";
export class ArchiveDisabledListController extends ListController {
    setup() {
        super.setup();
        this.archiveEnabled = false;
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
