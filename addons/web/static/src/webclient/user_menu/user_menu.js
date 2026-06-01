// @ts-check
/** @odoo-module native */

/** @module @web/webclient/user_menu/user_menu - Systray dropdown displaying current user avatar and menu items from the user_menuitems registry */

import { Component } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownGroup } from "@web/components/dropdown/dropdown_group";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { imageUrl } from "@web/core/utils/urls";
import { user } from "@web/services/user";
import { session } from "@web/session";

const userMenuRegistry = registry.category("user_menuitems");

// User-menu items are factory functions: (env) => { description, callback,
// sequence?, show?, ... }. The consumer (`getElements`, below) calls each
// entry with the env and treats the returned object as the menu item.
userMenuRegistry.addValidation((entry) => typeof entry === "function");

/**
 * Systray dropdown displaying the current user's avatar, name, and
 * menu items from the "user_menuitems" registry (preferences, log out, etc.).
 */
export class UserMenu extends Component {
    static template = "web.UserMenu";
    static components = { DropdownGroup, Dropdown, DropdownItem, CheckBox };
    static props = {};

    setup() {
        this.userName = user.name;
        this.dbName = session.db;
    }

    /**
     * Build the avatar URL lazily. Returning "" while ``user.partnerId`` is
     * still undefined avoids server requests with ``id=undefined``, which
     * the test runner catches as 500/404 noise (and which a non-test page
     * would render as a broken-image icon during the first paint).
     * The render-without-waiting-for-menus refactor makes this transient
     * window observable; without the guard, every initial mount fires a
     * doomed RPC.
     */
    get source() {
        const { partnerId, writeDate } = user;
        if (!partnerId) {
            return "";
        }
        return imageUrl("res.partner", partnerId, "avatar_128", {
            unique: writeDate,
        });
    }

    /** @returns {Object[]} sorted, visible user menu items */
    getElements() {
        const sortedItems = userMenuRegistry
            .getAll()
            .map((element) =>
                element(/** @type {import("@web/env").OdooEnv} */ (this.env)),
            )
            .filter((element) => (element.show ? element.show() : true))
            .sort((x, y) => {
                const xSeq = x.sequence ? x.sequence : 100;
                const ySeq = y.sequence ? y.sequence : 100;
                return xSeq - ySeq;
            });
        return sortedItems;
    }
}

export const systrayItem = {
    Component: UserMenu,
};
registry.category("systray").add("web.user_menu", systrayItem, { sequence: 0 });
