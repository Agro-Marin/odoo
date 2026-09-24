/** @odoo-module native */
import { ListRenderer } from "@web/views/list";
import { useService } from "@web/core/utils/hooks";

export class ImportModuleListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    get hasSelectors() {
        return (
            super.hasSelectors &&
            this.props.list.records.every(
                (record) => record.savedData.module_type != "industries",
            )
        );
    }

    async onCellClicked(record, column, ev) {
        if (
            record.savedData.module_type &&
            record.savedData.module_type !== "official"
        ) {
            const re_action = {
                name: "more_info",
                res_model: "ir.module.module",
                res_id: -1,
                type: "ir.actions.act_window",
                views: [[false, "form"]],
                context: {
                    module_name: record.savedData.name,
                    module_type: record.savedData.module_type,
                },
            };
            this.action.doAction(re_action);
        } else {
            super.onCellClicked(record, column, ev);
        }
    }
}
