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
            registry.category("systray").add(
                "web.debug_mode_menu",
                {
                    Component: /** @type {any} */ (DebugMenu),
                },
                { sequence: 100 },
            );
        }
        this.localization = localization;
        this.state = useState({
            fullscreen: false,
        });
        // The route-change load rides the action manager's shared KeepLast; if
        // a newer doAction supersedes it (Ctrl+K palette, hotkey-triggered
        // button...), loadRouterState rejects with a SupersededError, which the
        // error service swallows. No escape hatch needed — supersession is now
        // observable (was: a pointer-events freeze/thaw workaround around a
        // never-settling promise).
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
            // the chat window and dialog services listen to 'web_client_ready' event in
            // order to initialize themselves:
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
        // ** url-retrocompatibility **
        // the menu_id in the url is only possible if we came from an old url
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
        // Read once, up front: both the URL resolution below and the
        // post-load fallback must see the same value, and `setCurrentMenu`
        // rewrites the key in between.
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
                // A newer navigation superseded this route change; it owns the
                // UI now. Re-throw so the error service swallows it silently —
                // do NOT fall back to the default app (that would fight the
                // newer navigation).
                throw error;
            }
            // Still surface the error (dialog) but don't let it strand the
            // webclient: with nothing on screen, load the default app; with
            // a controller already displayed, keep it. Don't fall through to
            // the retrocompat branches — they would re-derive (and re-run)
            // an action from the same broken state.
            Promise.reject(error);
            if (!this.actionService.currentController) {
                await this._loadDefaultApp();
            }
            return;
        }

        // ** url-retrocompatibility **
        // when there is only menu_id in url
        if (!stateLoaded && menuId) {
            const actionId = this.menuService.getMenu(menuId)?.actionID;
            if (actionId) {
                await this.actionService.doAction(actionId, {
                    clearBreadcrumbs: true,
                });
                stateLoaded = true;
            }
        }

        // Setting the menu based on the action after it was loaded (eg when the
        // action in url is an xmlid)
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
            // If no action => falls back to the default app
            await this._loadDefaultApp();
        }
    }

    /** Navigate to the first root menu app as a fallback. */
    _loadDefaultApp() {
        const root = this.menuService.getMenu("root");
        const firstApp = root.children[0];
        if (firstApp) {
            // ``children`` is ``(number | string)[]``; ``selectMenu`` accepts
            // ``MenuItem | number``. Resolve through ``getMenu`` so the call
            // is type-clean regardless of which form the id takes.
            return this.menuService.selectMenu(this.menuService.getMenu(firstApp));
        }
    }

    /**
     * @param {MouseEvent} ev
     */
    onGlobalClick(ev) {
        // When a ctrl-click occurs inside an <a href/> element
        // we let the browser do the default behavior and
        // we do not want any other listener to execute.
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
