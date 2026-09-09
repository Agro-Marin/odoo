/** @odoo-module native */

import { rpc } from "@web/core/network";
import { patch } from "@web/core/utils/patch";
import { ExportDataDialog } from "@web/views/view_dialogs";

patch(ExportDataDialog.prototype, {
    async fetchFields(value) {
        await super.fetchFields(value);

        const analyticLineIdsField = this.knownFields["analytic_line_ids"];
        if (analyticLineIdsField) {
            this.state.exportList = this.state.exportList.filter(
                (field) => field.id !== "analytic_distribution",
            );
            const analyticLineFields = await rpc("/web/export/get_fields", {
                model: analyticLineIdsField.params.model,
                prefix: analyticLineIdsField.params.prefix,
                parent_name: analyticLineIdsField.params.parent_field.string,
                import_compat: analyticLineIdsField.default_export,
                parent_field_type: analyticLineIdsField.params.parent_field.type,
                domain: [],
            });
            const filteredAnalyticLineFields = analyticLineFields.filter(
                (field) =>
                    (field.params?.model === "account.analytic.account" &&
                        !field.id.includes("auto_account_id")) ||
                    field.id === "analytic_line_ids/amount",
            );

            this.state.exportList.push(...filteredAnalyticLineFields);
        }
    },
});
