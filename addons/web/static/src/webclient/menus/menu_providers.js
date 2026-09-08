// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { fuzzyLookup } from "@web/core/utils/search";
import { DefaultCommandItem } from "@web/ui/commands/command_palette";

import { menuUsage } from "./menu_usage.js";
import { flattenMenuTree, menuSearchKey } from "./menu_utils.js";

const RECENT_MENU_ITEMS = 5;

class AppIconCommand extends Component {
    static template = "web.AppIconCommand";
    static props = {
        webIconData: { type: String, optional: true },
        webIcon: { type: Object, optional: true },
        ...DefaultCommandItem.props,
    };
}

const commandCategoryRegistry = registry.category("command_categories");
commandCategoryRegistry.add("apps", { namespace: "/" }, { sequence: 10 });
commandCategoryRegistry.add("menu_items", { namespace: "/" }, { sequence: 20 });

const commandSetupRegistry = registry.category("command_setup");
commandSetupRegistry.add("/", {
    emptyMessage: _t("No menu found"),
    name: _t("menus"),
    placeholder: _t("Search for a menu..."),
});

const commandProviderRegistry = registry.category("command_provider");
commandProviderRegistry.add("menu", {
    namespace: "/",
    async provide(env, options) {
        const result = [];
        const menuService = env.services.menu;
        const computed = flattenMenuTree(menuService.getMenuAsTree("root"));
        const { menuItems } = computed;
        let { apps } = computed;
        /** @type {typeof menuItems} */
        let matchingItems;
        if (options.searchValue === "") {
            const recentApps = menuUsage.rank(apps);
            apps = [...recentApps, ...apps.filter((app) => !recentApps.includes(app))];
            matchingItems = menuUsage.rank(menuItems, RECENT_MENU_ITEMS);
        } else {
            apps = fuzzyLookup(options.searchValue, apps, (menu) => menu.label);
            matchingItems = fuzzyLookup(options.searchValue, menuItems, menuSearchKey, {
                preNormalized: true,
            });
        }
        matchingItems.forEach((menu) => {
            result.push({
                action() {
                    menuService.selectMenu(menu);
                },
                category: "menu_items",
                name: `${menu.parents} / ${menu.label}`,
                href: menu.href,
            });
        });

        apps.forEach((menu) => {
            const props = {};
            if (menu.webIconData) {
                props.webIconData = menu.webIconData;
            } else {
                props.webIcon = menu.webIcon;
            }
            result.push({
                Component: AppIconCommand,
                action() {
                    menuService.selectMenu(menu);
                },
                category: "apps",
                name: menu.label,
                href: menu.href,
                props,
            });
        });

        return result;
    },
});
