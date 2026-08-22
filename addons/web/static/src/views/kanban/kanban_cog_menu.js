// @ts-check
/** @odoo-module native */

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
