// @ts-check
/** @odoo-module native */

/** @module @web/webclient/webclient - Root OWL component bootstrapping the action manager, navbar, and main components container */

import { Component, onMounted, useExternalListener, useState } from "@odoo/owl";
import { MainComponentsContainer } from "@web/components/main_components_container";
import { browser } from "@web/core/browser/browser";
import { router, routerBus } from "@web/core/browser/router";
import { AppEvent, RouterEvent } from "@web/core/events";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { SupersededError } from "@web/core/utils/concurrency";
import { useBus, useService } from "@web/core/utils/hooks";
import { useOwnDebugContext } from "@web/services/debug/debug_context";
import { DebugMenu } from "@web/services/debug/debug_menu";

import { ActionContainer } from "./actions/action_container.js";
import { NavBar } from "./navbar/navbar.js";

/**
 * Root OWL component of the Odoo web client.
 *
 * Bootstraps the action manager, navbar, and main components container.
 * Handles route changes, menu resolution, and the global ctrl-click
 * passthrough for anchor elements. (Service-worker registration moved to the
 * ``service_worker`` service — see ``service_worker_service.js``.)
 */
export class WebClient extends Component {
    static template = "web.WebClient";
    static props = {};
    static components = {
        ActionContainer,
        NavBar,
        MainComponentsContainer,
    };

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
        useBus(
            this.env.bus,
            AppEvent.ACTION_MANAGER_UI_UPDATED,
            /** @type {any} */ (
                ({ detail: mode }) => {
                    if (mode !== "new") {
                        this.state.fullscreen = mode === "fullscreen";
                    }
                }
            ),
        );
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
     * Resolve which app the current URL belongs to.
     *
     * Two spellings must be handled: a legacy ``menu_id`` query parameter, and
     * (the normal case) the root action of the URL's action stack, which is
     * mapped back to an app through the menu service's action index. When
     * several apps expose the same action, the one the user was last in wins.
     *
     * @param {number} storedMenuId the app the user was last in (tie-breaker)
     * @returns {number} the app id, or 0 when the URL names none
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

    /**
     * Scroll to the URL's anchor, if it names one and it resolves. The hash is
     * user-controlled, so an invalid selector is expected input, not an error.
     */
    _scrollToUrlAnchor() {
        if (browser.location.hash === "") {
            return;
        }
        try {
            document.querySelector(browser.location.hash)?.scrollIntoView(true);
        } catch {
            // do nothing if the hash is not a correct selector.
        }
    }

    /** Resolve the current URL state to an action + menu, then load it. */
    async loadRouterState() {
        const storedMenuId = Number(browser.sessionStorage.getItem("menu_id"));
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
            Promise.reject(error);
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

    /**
     * Navigate to the first app as a fallback.
     *
     * Through ``getApps()`` rather than ``getMenu("root").children[0]``: the
     * menu tree can come from a ``localStorage`` copy that parses but names a
     * menu id it does not define, and the raw spelling then landed the user on
     * a dangling id — or threw outright when the payload had no ``root``.
     */
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
