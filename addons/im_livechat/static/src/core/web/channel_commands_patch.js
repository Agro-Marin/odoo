/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

registry.category("discuss.channel_commands").add("history", {
    condition: ({ store }) => store.has_access_livechat,
    channel_types: ["livechat"],
    help: _t("See 15 last visited pages"),
    methodName: "execute_command_history",
});
