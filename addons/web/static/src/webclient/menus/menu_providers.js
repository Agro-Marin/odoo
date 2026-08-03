// @ts-check
/** @odoo-module native */

/** @module @web/webclient/menus/menu_providers */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { fuzzyLookup } from "@web/core/utils/search";
import { DefaultCommandItem } from "@web/ui/commands/command_palette";

import { computeAppsAndMenuItems } from "./menu_helpers.js";

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

/**
 * The palette re-queries every provider on each keystroke, and the tree it
 * flattens only changes when the menu service rebuilds it — `getMenuAsTree`
 * hands back the same object until then, which makes it the cache key.
 *
 * @type {WeakMap<object, ReturnType<typeof computeAppsAndMenuItems>>}
 */
const flattenedTrees = new WeakMap();

/** @param {object} tree */
function flattenMenuTree(tree) {
    let flattened = flattenedTrees.get(tree);
    if (!flattened) {
        flattened = computeAppsAndMenuItems(tree);
        flattenedTrees.set(tree, flattened);
    }
    return flattened;
}

const commandProviderRegistry = registry.category("command_provider");
commandProviderRegistry.add("menu", {
    namespace: "/",
    async provide(env, options) {
        const result = [];
        const menuService = env.services.menu;
        const computed = flattenMenuTree(menuService.getMenuAsTree("root"));
        const { menuItems } = computed;
        let { apps } = computed;
        if (options.searchValue !== "") {
            apps = fuzzyLookup(options.searchValue, apps, (menu) => menu.label);

            fuzzyLookup(options.searchValue, menuItems, (menu) =>
                `${menu.parents} / ${menu.label}`.split("/").reverse().join("/"),
            ).forEach((menu) => {
                result.push({
                    action() {
                        menuService.selectMenu(menu);
                    },
                    category: "menu_items",
                    name: `${menu.parents} / ${menu.label}`,
                    href: menu.href,
                });
            });
        }

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
