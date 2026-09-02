/** @odoo-module native */
import { ListRenderer } from "@web/views/list";

export class ImportModuleListRenderer extends ListRenderer {
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
            this.env.services.action.doAction(re_action);
        } else {
            super.onCellClicked(record, column, ev);
        }
    }
}
