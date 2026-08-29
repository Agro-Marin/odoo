/** @odoo-module native */
import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ACTIONS_GROUP_NUMBER } from "@web/search/action_menus/action_menus";

const cogMenuRegistry = registry.category("cogMenu");

/**
 * Re-run every recycling rule without opening any of them.
 *
 * The queue is derived data: it only reflects what the rules select as of the
 * last run. Until now the only way to refresh it was the Run Now button on a
 * rule's own form, one rule at a time, or waiting for the scheduled action.
 */
export class RefreshQueueCogMenu extends Component {
    static template = "data_recycle.RefreshQueueCogMenu";
    static components = { DropdownItem };
    static props = {};

    setup() {
        this.orm = useService("orm");
    }

    async refreshQueue() {
        await this.orm.call("data_recycle.model", "action_refresh_records", [[]]);
        // Reload the queue in place. The rule picked in the search panel, and
        // every other facet, is part of the search state and stays as it was --
        // which re-opening the action would have thrown away.
        await this.env.searchModel.refresh();
    }
}

export const refreshQueueCogMenuItem = {
    Component: RefreshQueueCogMenu,
    groupNumber: ACTIONS_GROUP_NUMBER,
    isDisplayed: ({ config, searchModel }) =>
        searchModel.resModel === "data_recycle.record" && config.viewType === "list",
};

cogMenuRegistry.add("data_recycle-refresh-queue", refreshQueueCogMenuItem);
