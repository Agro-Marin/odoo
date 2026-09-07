// @ts-check
/** @odoo-module native */

import { Component, onMounted, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { menuUsage } from "@web/webclient/menus/menu_usage";

import { appBadge, loadHomeMenuBadges } from "./badges.js";
import { pinnedApps, shownApps } from "./home_menu_layout.js";
import { computeHomeMenuLayout } from "./home_menu_service.js";

const TILES = 12;

/**
 * The app launcher reachable from inside an app: a popover under the navbar's
 * home toggle with the pinned apps, then the recent ones, then the rest up to
 * a dozen, each with its badge, and a search box that hands off to the palette.
 * The full home menu stays one click away for everything else.
 */
export class QuickLauncher extends Component {
    static template = "web.QuickLauncher";
    static props = { close: Function };

    /** @type {import("services").ServiceFactories["menu"]} */
    menus;
    /** @type {import("services").ServiceFactories["home_menu"]} */
    homeMenu;
    /** @type {import("services").ServiceFactories["command"]} */
    command;
    /** @type {{ badges: Record<string, number> }} */
    state;
    /** @type {import("./home_menu.js").HomeMenuApp[]} */
    apps;

    setup() {
        this.menus = useService("menu");
        this.homeMenu = useService("home_menu");
        this.command = useService("command");
        this.state = useState({ badges: {} });
        // The layout, not the home menu's props: the popover reorders
        // nothing, so it needs neither the reactive wrappers nor the callbacks.
        const { apps, config } = computeHomeMenuLayout(this.menus);
        this.apps = this._pickApps(apps, config);
        // Counts arrive after the tiles: a slow provider must not hold the popover.
        onMounted(async () => {
            this.state.badges = await loadHomeMenuBadges(
                /** @type {import("@web/env").OdooEnv} */ (
                    /** @type {unknown} */ (this.env)
                ),
                this.apps,
            );
        });
    }

    /**
     * @param {import("./home_menu.js").HomeMenuApp[]} apps in the stored order
     * @param {import("@web/webclient/menus/menu_utils").HomeMenuConfig} config
     */
    _pickApps(apps, config) {
        const shown = shownApps(config, apps);
        // Pinned first, then what the user opens, then the rest in the stored
        // order; the Set keeps the first appearance of each.
        const ordered = [
            ...pinnedApps(config, shown),
            ...menuUsage.rank(shown),
            ...shown,
        ];
        return [...new Set(ordered)].slice(0, TILES);
    }

    /** @param {import("./home_menu.js").HomeMenuApp} app */
    badgeFor(app) {
        return appBadge(this.state.badges, app);
    }

    /** @param {import("./home_menu.js").HomeMenuApp} app */
    onAppClick(app) {
        // Issue the navigation before the popover unmounts this component.
        const opened = this.menus.selectMenu(app);
        this.props.close();
        return opened;
    }

    onAllAppsClick() {
        const opened = this.homeMenu.toggle(true);
        this.props.close();
        return opened;
    }

    /** @param {InputEvent} ev */
    onSearchInput(ev) {
        const typed = /** @type {HTMLInputElement} */ (ev.target).value.trim();
        if (!typed) {
            return;
        }
        this.props.close();
        this.command.openMainPalette(/** @type {any} */ ({ searchValue: `/${typed}` }));
    }
}
