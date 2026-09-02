// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { GroupConfigMenu } from "@web/views/view_components";

import { PromoteStudioAutomationDialog } from "./promote_studio_dialog.js";

patch(GroupConfigMenu.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
    },
    /**
     * @override
     */
    get permissions() {
        const permissions = super.permissions;
        Object.defineProperty(permissions, "canEditAutomations", {
            get: () => user.isAdmin,
            configurable: true,
        });
        return permissions;
    },

    async openAutomations() {
        if (typeof this._openAutomations === "function") {
            // this is the case if automation is installed
            return this._openAutomations();
        } else {
            this.dialog.add(PromoteStudioAutomationDialog, {
                title: _t("Odoo Studio - Customize workflows in minutes"),
            });
        }
    },
});

registry.category("group_config_items").add(
    "open_automations",
    {
        label: _t("Automations"),
        method: "openAutomations",
        isVisible: ({ permissions }) =>
            /** @type {any} */ (permissions).canEditAutomations,
        class: "o_column_automations",
        icon: "fa-magic",
    },
    { sequence: 25, force: true },
);
