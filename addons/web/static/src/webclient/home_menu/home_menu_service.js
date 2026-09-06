// @ts-check
/** @odoo-module native */

import { Component, onMounted, onWillUnmount, reactive, xml } from "@odoo/owl";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { Mutex } from "@web/core/utils/concurrency";
import { useBus, useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import {
    ControllerNotFoundError,
    standardActionServiceProps,
} from "@web/webclient/actions";
import {
    computeAppsAndMenuItems,
    isDefaultHomeMenuConfig,
    parseHomeMenuConfig,
    reorderApps,
} from "@web/webclient/menus/menu_utils";

import { HomeMenu } from "./home_menu.js";

export class HomeMenuState {
    hasHomeMenu = false;
    hasBackgroundAction = false;

    /** @param {import("@web/env").OdooEnv} env */
    constructor(env) {
        this.action = env.services.action;
        this.mutex = new Mutex();
    }

    /** @param {boolean} [show] */
    async toggle(show) {
        // A navigation minted after this request outranks the menu: the
        // client's start-up default-app load runs behind this mutex, and must
        // not supersede what the user opened meanwhile.
        const { action } = this;
        const epoch = action.navigation.epoch;
        return this.mutex.exec(async () => {
            show = show === undefined ? !this.hasHomeMenu : Boolean(show);
            if (show === this.hasHomeMenu) {
                return;
            }
            if (show) {
                if (action.navigation.epoch === epoch) {
                    await action.doAction("menu");
                }
                return;
            }
            try {
                await action.restore();
            } catch (err) {
                if (!(err instanceof ControllerNotFoundError)) {
                    throw err;
                }
            }
        });
    }
}

/**
 * @param {import("services").ServiceFactories["menu"]} menus
 * @returns {import("./home_menu.js").HomeMenu["props"]}
 */
export function computeHomeMenuProps(menus) {
    // The company's default applies until the user has a layout of their own;
    // a layout is the user's whole answer, never a per-field merge.
    const defaultConfig = parseHomeMenuConfig(session.homemenu_default_config);
    const own = parseHomeMenuConfig(user.settings?.homemenu_config);
    const config = reactive(
        isDefaultHomeMenuConfig(own) ? parseHomeMenuConfig(defaultConfig) : own,
    );
    const apps = reactive(computeAppsAndMenuItems(menus.getMenuAsTree("root")).apps);
    const defaultOrder = apps.flatMap((app) =>
        app.xmlid === undefined ? [] : [app.xmlid],
    );
    if (config.order.length) {
        reorderApps(apps, config.order);
    }
    return {
        apps,
        config,
        defaultConfig,
        reorderApps: (/** @type {string[]} */ order) => reorderApps(apps, order),
        resetApps: () => {
            reorderApps(apps, defaultOrder);
            if (defaultConfig.order.length) {
                reorderApps(apps, defaultConfig.order);
            }
        },
    };
}

export class HomeMenuAction extends Component {
    static components = { HomeMenu };
    static target = "current";
    static props = { ...standardActionServiceProps };
    static template = xml`<HomeMenu t-props="homeMenuProps"/>`;
    static displayName = _t("Home");

    /** @type {import("services").ServiceFactories["menu"]} */
    menus;
    /** @type {import("services").ServiceFactories["home_menu"]} */
    homeMenu;

    setup() {
        this.menus = useService("menu");
        this.homeMenu = useService("home_menu");
        this.homeMenuProps = computeHomeMenuProps(this.menus);
        onMounted(() => this.onMounted());
        onWillUnmount(() => this.onWillUnmount());
        useBus(this.env.bus, AppEvent.MENUS_APP_CHANGED, () => {
            this.homeMenuProps = computeHomeMenuProps(this.menus);
            this.render();
        });
    }
    onMounted() {
        const { breadcrumbs } = this.env.config;
        this.homeMenu.hasHomeMenu = true;
        this.homeMenu.hasBackgroundAction = breadcrumbs.length > 0;
        this.env.bus.trigger(AppEvent.HOME_MENU_TOGGLED);
    }
    onWillUnmount() {
        this.homeMenu.hasHomeMenu = false;
        this.homeMenu.hasBackgroundAction = false;
        this.env.bus.trigger(AppEvent.HOME_MENU_TOGGLED);
    }
}

export const homeMenuService = {
    dependencies: ["action"],
    /** @param {import("@web/env").OdooEnv} env */
    start(env) {
        const state = reactive(new HomeMenuState(env));
        registry.category("actions").add("menu", HomeMenuAction);
        env.bus.addEventListener(AppEvent.HOME_MENU_TOGGLED, () => {
            document.body.classList.toggle("o_home_menu_background", state.hasHomeMenu);
        });
        return state;
    },
};

registry.category("services").add("home_menu", homeMenuService);
