// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_cog_menu - Kanban cog menu that hides registry items during multi-select operations */

/** Hides registry items during multi-select; only selection-specific actions remain visible. */
import { CogMenu } from "@web/search/cog_menu/cog_menu";
export class KanbanCogMenu extends CogMenu {
    static template = "web.KanbanCogMenu";
    static props = {
        ...CogMenu.props,
        hasSelectedRecords: { type: [Boolean, Number], optional: true },
    };
    _registryItems() {
        return /** @type {any} */ (
            this.props.hasSelectedRecords ? [] : super._registryItems()
        );
    }
}
