// @ts-check
/** @odoo-module native */

import { Component, markRaw, onMounted, onWillUnmount, reactive, xml } from "@odoo/owl";
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
    flattenMenuTree,
    parseHomeMenuConfig,
    readHomeMenuConfig,
    reorderApps,
} from "@web/webclient/menus/menu_utils";

import { HomeMenu } from "./home_menu.js";
import { useHomeMenuLayoutSync } from "./home_menu_layout.js";

export class HomeMenuState {
    hasHomeMenu = false;
    hasBackgroundAction = false;

    /** @param {import("@web/env").OdooEnv} env */
    constructor(env) {
        // Services must stay raw: proxying their controller state breaks
        // structured cloning when the action service writes browser history.
        this.action = markRaw(env.services.action);
        this.mutex = markRaw(new Mutex());
    }

    /** @param {boolean} [show] */
    async toggle(show) {
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
 * @returns {{
 *  apps: import("./home_menu.js").HomeMenuApp[],
 *  config: import("@web/webclient/menus/menu_utils").HomeMenuConfig,
 *  defaultConfig: import("@web/webclient/menus/menu_utils").HomeMenuConfig,
 *  defaultOrder: string[],
 *  personal: boolean,
 * }}
 */
export function computeHomeMenuLayout(menus) {
    const defaultConfig = parseHomeMenuConfig(session.homemenu_default_config);
    const own = readHomeMenuConfig(user.settings?.homemenu_config);
    const config = own ?? parseHomeMenuConfig(defaultConfig);
    const apps = [...flattenMenuTree(menus.getMenuAsTree("root")).apps];
    const defaultOrder = apps.flatMap((app) =>
        app.xmlid === undefined ? [] : [app.xmlid],
    );
    if (config.order.length) {
        reorderApps(apps, config.order);
    }
    return { apps, config, defaultConfig, defaultOrder, personal: own !== null };
}

/**
 * @param {import("services").ServiceFactories["menu"]} menus
 * @returns {import("./home_menu.js").HomeMenu["props"]}
 */
export function computeHomeMenuProps(menus) {
    const layout = computeHomeMenuLayout(menus);
    const { defaultConfig, defaultOrder } = layout;
    const apps = reactive(layout.apps);
    const config = reactive(layout.config);
    return {
        apps,
        config,
        defaultConfig,
        personal: layout.personal,
        reorderApps: (/** @type {string[]} */ order) => reorderApps(apps, order),
        resetApps: (/** @type {string[]} */ order) => {
            reorderApps(apps, defaultOrder);
            if (order?.length) {
                reorderApps(apps, order);
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
        const refresh = () => {
            this.homeMenuProps = computeHomeMenuProps(this.menus);
            this.render();
        };
        useBus(this.env.bus, AppEvent.MENUS_APP_CHANGED, refresh);
        useHomeMenuLayoutSync(refresh);
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
