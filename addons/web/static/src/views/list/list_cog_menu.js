// @ts-check
/** @odoo-module native */

import { CogMenu } from "@web/search/cog_menu/cog_menu";
export class ListCogMenu extends CogMenu {
    static template = "web.ListCogMenu";
    static props = {
        ...CogMenu.props,
        hasSelectedRecords: { type: [Boolean, Number], optional: true },
    };
    /**
     * @override
     * @returns {any}
     */
    _registryItems() {
        return this.props.hasSelectedRecords ? [] : super._registryItems();
    }
}
