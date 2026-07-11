// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_cog_menu - List-view cog menu that hides registry items when records are selected */

/** When records are selected, shows only action menus (print, action) and hides registry items (e.g. export). */
import { CogMenu } from "@web/search/cog_menu/cog_menu";
export class ListCogMenu extends CogMenu {
    static template = "web.ListCogMenu";
    static props = {
        ...CogMenu.props,
        // Boolean in the base controller; Number tolerated for controller
        // subclasses whose getter returns a count (e.g. documents).
        hasSelectedRecords: { type: [Boolean, Number], optional: true },
    };
    /** @override @returns {any} */
    _registryItems() {
        return this.props.hasSelectedRecords ? [] : super._registryItems();
    }
}
