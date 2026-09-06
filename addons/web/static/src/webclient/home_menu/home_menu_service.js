// @ts-check
/** @odoo-module native */

import { Component, onMounted, onWillUnmount, reactive, xml } from "@odoo/owl";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { Mutex } from "@web/core/utils/concurrency";
import { useBus, useService } from "@web/core/utils/hooks";
import {
    ControllerNotFoundError,
    standardActionServiceProps,
} from "@web/webclient/actions";
import { computeAppsAndMenuItems, reorderApps } from "@web/webclient/menus/menu_utils";

import { HomeMenu } from "./home_menu.js";

export const homeMenuService = {
    dependencies: ["action"],
    /** @param {import("@web/env").OdooEnv} env */
    start(env) {
        const mutex = new Mutex();
        class HomeMenuState {
            hasHomeMenu = false;
            hasBackgroundAction = false;

            /** @param {boolean} [show] */
            async toggle(show) {
                // A navigation minted after this request outranks the menu:
                // the client's start-up default-app load runs behind this
                // mutex, and must not supersede what the user opened meanwhile.
                const { navigation } = env.services.action;
                const epoch = navigation.epoch;
                return mutex.exec(async () => {
                    show = show === undefined ? !state.hasHomeMenu : Boolean(show);
                    if (show !== state.hasHomeMenu) {
                        if (show) {
                            if (navigation.epoch !== epoch) {
                                return;
                            }
                            await env.services.action.doAction("menu");
                        } else {
                            try {
                                await env.services.action.restore();
                            } catch (err) {
                                if (!(err instanceof ControllerNotFoundError)) {
                                    throw err;
                                }
                            }
                        }
                    }
                });
            }
        }
        const state = reactive(new HomeMenuState());
        class HomeMenuAction extends Component {
            static components = { HomeMenu };
            static target = "current";
            static props = { ...standardActionServiceProps };
            static template = xml`<HomeMenu t-props="homeMenuProps"/>`;
            static displayName = _t("Home");

            /** @type {import("services").ServiceFactories["menu"]} */
            menus;

            setup() {
                this.menus = useService("menu");
                onMounted(() => this.onMounted());
                onWillUnmount(this.onWillUnmount);
                useBus(this.env.bus, AppEvent.MENUS_APP_CHANGED, () => this.render());
            }
            get homeMenuProps() {
                const homemenuConfig = JSON.parse(
                    user.settings?.homemenu_config || "null",
                );
                const apps = reactive(
                    computeAppsAndMenuItems(this.menus.getMenuAsTree("root")).apps,
                );
                if (homemenuConfig) {
                    reorderApps(apps, homemenuConfig);
                }
                return {
                    apps,
                    reorderApps: (/** @type {string[]} */ order) =>
                        reorderApps(apps, order),
                };
            }
            onMounted() {
                const { breadcrumbs } = this.env.config;
                state.hasHomeMenu = true;
                state.hasBackgroundAction = breadcrumbs.length > 0;
                this.env.bus.trigger(AppEvent.HOME_MENU_TOGGLED);
            }
            onWillUnmount() {
                state.hasHomeMenu = false;
                state.hasBackgroundAction = false;
                this.env.bus.trigger(AppEvent.HOME_MENU_TOGGLED);
            }
        }

        registry.category("actions").add("menu", HomeMenuAction);

        env.bus.addEventListener(AppEvent.HOME_MENU_TOGGLED, () => {
            document.body.classList.toggle("o_home_menu_background", state.hasHomeMenu);
        });

        return state;
    },
};

registry.category("services").add("home_menu", homeMenuService);
