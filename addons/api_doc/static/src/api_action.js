/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

registry.category("actions").add("doc_api_key_wizard", () => ({
    type: "ir.actions.act_window",
    name: _t("API Key Wizard"),
    res_model: "res.users.apikeys.description",
    views: [[false, "form"]],
    target: "new",
}));
