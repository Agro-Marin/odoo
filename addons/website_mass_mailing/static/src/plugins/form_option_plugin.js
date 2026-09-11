/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { FormOptionPlugin } from "@website/builder/plugins/form/form_option_plugin";

patch(FormOptionPlugin.prototype, {
    async _fetchFieldRecords(field) {
        if (field.name === "list_ids" && field.relation === "mailing.list") {
            field.fieldName = "name";
        }
        return super._fetchFieldRecords(...arguments);
    },
});
