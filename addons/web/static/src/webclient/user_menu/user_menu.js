// @ts-check
/** @odoo-module native */

/** @module @web/webclient/user_menu/user_menu */

import { Component } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownGroup } from "@web/components/dropdown/dropdown_group";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { imageUrl } from "@web/core/utils/urls";
import { session } from "@web/session";

const userMenuRegistry = registry.category("user_menuitems");

userMenuRegistry.addValidation((entry) => typeof entry === "function");

export class UserMenu extends Component {
    static template = "web.UserMenu";
    static components = { DropdownGroup, Dropdown, DropdownItem, CheckBox };
    static props = {};

    setup() {
        this.userName = user.name;
        this.dbName = session.db;
    }

    get source() {
        const { partnerId, writeDate } = user;
        if (!partnerId) {
            return "";
        }
        return imageUrl("res.partner", partnerId, "avatar_128", {
            unique: writeDate,
        });
    }

    /**
     * Each element carries the registry key it was built from, so the menu can
     * be keyed by identity: `show()` is re-evaluated on every render (the PWA
     * entry appears once the browser offers an install prompt), and keying such
     * a list by index makes OWL reconcile every entry after the insertion point
     * against the wrong element.
     *
     * @returns {Object[]}
     */
    getElements() {
        const sortedItems = userMenuRegistry
            .getEntries()
            .map(([key, element]) => ({
                ...element(/** @type {import("@web/env").OdooEnv} */ (this.env)),
                // Last, so the registry key always wins: `t-key` needs it unique.
                key,
            }))
            .filter(
                (element) => !element.hide && (element.show ? element.show() : true),
            )
            .sort((x, y) => (x.sequence ?? 100) - (y.sequence ?? 100));
        return sortedItems;
    }
}

export const systrayItem = {
    Component: UserMenu,
};
registry.category("systray").add("web.user_menu", systrayItem, { sequence: 0 });
