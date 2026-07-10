// @ts-check
/** @odoo-module native */

/** @module @web/views/list/export_all/export_all - Cog-menu item triggering direct XLSX export of all records */

import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { SearchModelEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { STATIC_ACTIONS_GROUP_NUMBER } from "@web/search/action_menus/action_menus";
import { user } from "@web/services/user";

const cogMenuRegistry = registry.category("cogMenu");

/** @extends Component */
export class ExportAll extends Component {
    static template = "web.ExportAll";
    static components = { DropdownItem };
    static props = {};

    // Protected

    /** Trigger a direct XLSX export of all records via the search model event bus. */
    async onDirectExportData() {
        this.env.searchModel.trigger(SearchModelEvent.DIRECT_EXPORT_DATA);
    }
}

const exportAllItem = /** @type {any} */ ({
    Component: ExportAll,
    groupNumber: STATIC_ACTIONS_GROUP_NUMBER,
    isDisplayed: async (/** @type {any} */ env) =>
        ["kanban", "list"].includes(env.config.viewType) &&
        !env.model.root.selection.length &&
        (await user.hasGroup("base.group_allow_export")) &&
        exprToBoolean(env.config.viewArch.getAttribute("export_xlsx"), true),
});

cogMenuRegistry.add("export-all-menu", exportAllItem, { sequence: 10 });
