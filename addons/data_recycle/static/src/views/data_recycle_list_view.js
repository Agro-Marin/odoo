/** @odoo-module native */
import { DataCleaningCommonListController } from "@data_recycle/views/data_cleaning_common_list";
import { _t } from "@web/core/translation";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list";

export class DataRecycleListController extends DataCleaningCommonListController {
    /**
     * Validate all the records selected
     */
    async onValidateClick() {
        const list = this.model.root;
        const resIds = await list.getResIds(true);

        await this.orm.call("data_recycle.record", "action_validate", [resIds]);
        // "Select all" resolves to at most `activeIdsLimit` ids: without this the
        // rest is silently left behind and the list just looks like it did not work.
        list._warnIfTruncated(resIds, () =>
            _t(
                "Of the %(selectedRecords)s selected records, only the first %(firstRecords)s have been recycled.",
                { selectedRecords: list.recordCount, firstRecords: resIds.length },
            ),
        );
        await this.model.load();
    }
}

registry.category("views").add("data_recycle_list", {
    ...listView,
    Controller: DataRecycleListController,
    buttonTemplate: "DataRecycle.buttons",
});
