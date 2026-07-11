// @ts-check
/** @odoo-module native */

/** @module @web/webclient/webclient - Root OWL component bootstrapping the action manager, navbar, and main components container */

import {
    Component,
    onMounted,
    onWillStart,
    useExternalListener,
    useState,
} from "@odoo/owl";
import { MainComponentsContainer } from "@web/components/main_components_container";
import { browser } from "@web/core/browser/browser";
import { router, routerBus } from "@web/core/browser/router";
import { AppEvent, RouterEvent, RpcEvent } from "@web/core/events";
import { localization } from "@web/core/l10n/localization";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";
import { useBus, useService } from "@web/core/utils/hooks";
import { useOwnDebugContext } from "@web/services/debug/debug_context";
import { DebugMenu } from "@web/services/debug/debug_menu";

import { ActionContainer } from "./actions/action_container.js";
import { NavBar } from "./navbar/navbar.js";

/**
 * Root OWL component of the Odoo web client.
 *
 * Bootstraps the action manager, navbar, and main components container.
 * Handles route changes, menu resolution, service worker registration,
 * and the global ctrl-click passthrough for anchor elements.
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
        useBus(routerBus, RouterEvent.ROUTE_CHANGE, async () => {
            document.body.style.pointerEvents = "none";
            // The route-change load rides the action manager's shared
            // KeepLast: if another doAction supersedes it (Ctrl+K palette,
            // hotkey-triggered button...), the awaited promise NEVER settles
            // and the finally would never restore pointer events — a
            // permanently mouse-dead page. Any completed action render is
            // therefore also a restore signal (idempotent).
            const restore = () => {
                document.body.style.pointerEvents = "auto";
                this.env.bus.removeEventListener(
                    AppEvent.ACTION_MANAGER_UI_UPDATED,
                    restore,
                );
            };
            this.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UI_UPDATED, restore);
            try {
                await this.loadRouterState();
            } finally {
                restore();
            }
        });
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
        this.serviceWorkerActivatedDeferred = new Deferred();
        // Fire-and-forget: don't block the first render on service worker
        // registration/activation (if the SW install stalls, awaiting
        // ``navigator.serviceWorker.ready`` would never resolve and leave a
        // blank page). ``registerServiceWorker`` catches its own errors.
        onWillStart(() => {
            this.registerServiceWorker();
        });
    }

    /** Resolve the current URL state to an action + menu, then load it. */
    async loadRouterState() {
        // ** url-retrocompatibility **
        // the menu_id in the url is only possible if we came from an old url
        let menuId = Number(router.current.menu_id || 0);
        const storedMenuId = Number(browser.sessionStorage.getItem("menu_id"));
        const firstAction = router.current.actionStack?.[0]?.action;
        if (!menuId && firstAction) {
            const matchingMenus = this.menuService
                .getAll()
                .filter(
                    (m) => m.actionID === firstAction || m.actionPath === firstAction,
                );

            if (matchingMenus.length) {
                menuId = matchingMenus.find((m) => m.appID === storedMenuId)?.appID;
                if (!menuId) {
                    menuId = matchingMenus[0]?.appID;
                }
            }
        }
        if (menuId) {
            this.menuService.setCurrentMenu(menuId);
        }
        let stateLoaded;
        try {
            stateLoaded = await this.actionService.loadState();
        } catch (error) {
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
            const menu = this.menuService.getAll().find((m) => menuId === m.id);
            const actionId = menu?.actionID;
            if (actionId) {
                await this.actionService.doAction(actionId, {
                    clearBreadcrumbs: true,
                });
                stateLoaded = true;
            }
        }

        // Setting the menu based on the action after it was loaded (eg when the action in url is an xmlid)
        if (stateLoaded && !menuId) {
            const currentController = this.actionService.currentController;
            const actionId = currentController?.action.id;
            menuId = this.menuService
                .getAll()
                .find((m) => m.actionID === actionId)?.appID;
            if (!menuId) {
                menuId = storedMenuId;
            }
            if (menuId) {
                this.menuService.setCurrentMenu(menuId);
            }
        }

        // Scroll to anchor after the state is loaded
        if (stateLoaded) {
            if (browser.location.hash !== "") {
                try {
                    const el = document.querySelector(browser.location.hash);
                    if (el !== null) {
                        el.scrollIntoView(true);
                    }
                } catch {
                    // do nothing if the hash is not a correct selector.
                }
            }
        }

        if (!stateLoaded) {
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

    /** Register the Odoo service worker for /odoo scope and resolve when activated. */
    async registerServiceWorker() {
        if (navigator.serviceWorker) {
            try {
                const registration = await navigator.serviceWorker.register(
                    "/web/service-worker.js",
                    { scope: "/odoo" },
                );
                if (registration.active && registration.active.state === "activated") {
                    this.serviceWorkerActivatedDeferred.resolve();
                } else {
                    const sw =
                        registration.installing ||
                        registration.waiting ||
                        registration.active;
                    sw.addEventListener("statechange", (e) => {
                        if (/** @type {any} */ (e.target).state === "activated") {
                            this.serviceWorkerActivatedDeferred.resolve();
                        }
                    });
                }
                await navigator.serviceWorker.ready;
                if (!navigator.serviceWorker.controller) {
                    // https://stackoverflow.com/questions/51597231/register-service-worker-after-hard-refresh
                    rpcBus.trigger(RpcEvent.CLEAR_CACHES);
                }
            } catch (error) {
                console.error("Service worker registration failed, error:", error);
            }
        }
    }
}
