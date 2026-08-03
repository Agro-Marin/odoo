// @ts-check
/** @odoo-module native */

/** @module @web/webclient/webclient */

import { Component, onMounted, useExternalListener, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { router, routerBus } from "@web/core/browser/router";
import { useOwnDebugContext } from "@web/core/debug/debug_context";
import { reportUncaught } from "@web/core/errors/error_utils";
import { AppEvent, RouterEvent } from "@web/core/events";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { SupersededError } from "@web/core/utils/concurrency";
import { useBus, useService } from "@web/core/utils/hooks";
import { MainComponentsContainer } from "@web/ui/main_components_container";
import { DebugMenu } from "@web/webclient/debug/debug_menu";

import { ActionContainer } from "./actions/action_container.js";
import { menuStorage } from "./menus/menu_storage.js";
import { NavBar } from "./navbar/navbar.js";

export class WebClient extends Component {
    static template = "web.WebClient";
    static props = {};
    static components = {
        ActionContainer,
        NavBar,
        MainComponentsContainer,
    };

    /** @type {import("services").ServiceFactories["action"]} */
    actionService;
    /** @type {import("services").ServiceFactories["menu"]} */
    menuService;
    /** @type {{ fullscreen: boolean }} */
    state;

    setup() {
        this.menuService = useService("menu");
        this.actionService = useService("action");
        this.title = useService("title");
        useOwnDebugContext({ categories: ["default"] });
        if (this.env.debug) {
            registry
                .category("systray")
                .add(
                    "web.debug_mode_menu",
                    { Component: DebugMenu },
                    { sequence: 100 },
                );
        }
        this.localization = localization;
        this.state = useState({
            fullscreen: false,
        });
        useBus(routerBus, RouterEvent.ROUTE_CHANGE, () => this.loadRouterState());
        useBus(this.env.bus, AppEvent.ACTION_MANAGER_UI_UPDATED, ({ detail: mode }) => {
            if (mode !== "new") {
                this.state.fullscreen = mode === "fullscreen";
            }
        });
        useBus(this.env.bus, AppEvent.WEBCLIENT_LOAD_DEFAULT_APP, this._loadDefaultApp);
        onMounted(() => {
            this.loadRouterState();
            this.env.bus.trigger(AppEvent.WEB_CLIENT_READY);
        });
        useExternalListener(window, "click", /** @type {any} */ (this.onGlobalClick), {
            capture: true,
        });
    }

    /**
     * @param {number} storedMenuId
     * @returns {number}
     */
    _resolveMenuFromUrl(storedMenuId) {
        const menuId = Number(router.current.menu_id || 0);
        if (menuId) {
            return menuId;
        }
        const firstAction = router.current.actionStack?.[0]?.action;
        if (!firstAction) {
            return 0;
        }
        return (
            Number(this.menuService.getAppIdByAction(firstAction, storedMenuId)) || 0
        );
    }

    _scrollToUrlAnchor() {
        if (browser.location.hash === "") {
            return;
        }
        try {
            document.querySelector(browser.location.hash)?.scrollIntoView(true);
        } catch {}
    }

    async loadRouterState() {
        const storedMenuId = menuStorage.readCurrentApp();
        let menuId = this._resolveMenuFromUrl(storedMenuId);
        if (menuId) {
            this.menuService.setCurrentMenu(menuId);
        }
        let stateLoaded;
        try {
            stateLoaded = await this.actionService.loadState();
        } catch (error) {
            if (error instanceof SupersededError) {
                throw error;
            }
            reportUncaught(error);
            if (!this.actionService.currentController) {
                await this._loadDefaultApp();
            }
            return;
        }

        if (!stateLoaded && menuId) {
            const actionId = this.menuService.getMenu(menuId)?.actionID;
            if (actionId) {
                await this.actionService.doAction(actionId, {
                    clearBreadcrumbs: true,
                });
                stateLoaded = true;
            }
        }

        if (stateLoaded && !menuId) {
            const actionId = this.actionService.currentController?.action.id;
            menuId =
                Number(this.menuService.getAppIdByAction(actionId)) || storedMenuId;
            if (menuId) {
                this.menuService.setCurrentMenu(menuId);
            }
        }

        if (stateLoaded) {
            this._scrollToUrlAnchor();
        } else {
            await this._loadDefaultApp();
        }
    }

    _loadDefaultApp() {
        const [firstApp] = this.menuService.getApps();
        if (firstApp) {
            return this.menuService.selectMenu(firstApp);
        }
    }

    /**
     * @param {MouseEvent} ev
     */
    onGlobalClick(ev) {
        if (
            (ev.ctrlKey || ev.metaKey) &&
            !(/** @type {any} */ (ev.target).isContentEditable) &&
            ((ev.target instanceof HTMLAnchorElement && ev.target.href) ||
                (ev.target instanceof HTMLElement &&
                    ev.target.closest("a[href]:not([href=''])")))
        ) {
            ev.stopImmediatePropagation();
            return;
        }
    }
}
