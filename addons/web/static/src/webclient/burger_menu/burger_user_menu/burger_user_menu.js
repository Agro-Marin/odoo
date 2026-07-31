// @ts-check
/** @odoo-module native */

/** @module @web/webclient/burger_menu/burger_user_menu/burger_user_menu */

import { UserMenu } from "@web/webclient/user_menu/user_menu";

export class BurgerUserMenu extends UserMenu {
    static template = "web.BurgerUserMenu";
    static props = {
        ...UserMenu.props,
        onMenuClicked: { type: Function, optional: true },
    };
    /**
     * @param {Function} callback
     * @returns {(ev: Event) => void}
     */
    _onItemClicked(callback) {
        return (ev) => {
            callback(ev);
            this.props.onMenuClicked?.(ev);
        };
    }
}
