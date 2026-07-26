// @ts-check
/** @odoo-module native */

/** @module @web/webclient/menus/menu_service - Service that loads, caches, and navigates the Odoo menu tree */

import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";

import { menuStorage } from "./menu_storage.js";

const loadMenusUrl = `/web/webclient/load_menus`;

/** Minimal tree used when nothing could be loaded — beats an exception on the
 * first ``getAll()``/``getApps()`` call and a blanked webclient. */
const EMPTY_MENUS = {
    root: { id: "root", children: [], name: "root", appID: "root" },
};

/**
 * Fetch the menu tree from the server.
 *
 * Conditional-fetch contract: when ``cachedHash`` (the value of the
 * ``X-Menus-Hash`` header persisted alongside the localStorage copy) is
 * passed, the server answers an empty ``304`` if the payload is unchanged —
 * resolved here as ``null`` — instead of re-sending the full payload (base64
 * app icons included) on every boot.
 *
 * @param {boolean} [reload] bypass the parse-time preload
 * @param {string} [cachedHash]
 * @returns {Promise<{menus: Object, hash?: string} | null>} the menus and their
 *  server-side hash, or ``null`` when the cached copy is confirmed up-to-date
 */
async function fetchMenus(reload, cachedHash) {
    if (!reload && /** @type {any} */ (odoo).loadMenusPromise) {
        // Parse-time preload from web.webclient_bootstrap: already normalized
        // to the same `{menus, hash} | null` shape (and already carries the
        // stored hash when it was valid).
        return /** @type {any} */ (odoo).loadMenusPromise;
    }
    const url = cachedHash
        ? `${loadMenusUrl}?hash=${encodeURIComponent(cachedHash)}`
        : loadMenusUrl;
    const res = await browser.fetch(url, { cache: "no-store" });
    if (res.status === 304) {
        return null;
    }
    if (!res.ok) {
        throw new Error("Error while fetching menus");
    }
    return {
        menus: await res.json(),
        hash: res.headers.get("X-Menus-Hash") || undefined,
    };
}

/**
 * The menu tree, plus the derived lookups the webclient needs.
 *
 * ``menusData`` is a flat map keyed by menu id (plus the ``"root"`` pseudo
 * entry), exactly as ``ir.ui.menu.load_web_menus`` builds it — the key IS the
 * ``id`` field, so ``getMenu(id)`` is the O(1) form of any ``id`` search.
 *
 * The action index is lazy and rebuilt whenever the tree is replaced: an app
 * lookup by action is what the URL→menu resolution needs on every route
 * change, and ``WebClient`` used to open-code it with repeated full scans over
 * ``getAll()`` because the service exposed no such accessor.
 */
class MenuTree {
    /** @param {Object} menusData */
    constructor(menusData) {
        this.setData(menusData);
        /** @type {number | string | undefined} */
        this.currentAppId = undefined;
    }

    /** @param {Object} menusData */
    setData(menusData) {
        this.menusData = menusData || EMPTY_MENUS;
        /** @type {Map<number|string, Object> | null} lazy action -> app index */
        this._appByAction = null;
    }

    /** @param {number|string} menuId */
    getMenu(menuId) {
        return this.menusData[menuId];
    }

    getAll() {
        return Object.values(this.menusData);
    }

    getApps() {
        return this.getMenu("root").children.map((mid) => this.getMenu(mid));
    }

    getCurrentApp() {
        return this.currentAppId ? this.getMenu(this.currentAppId) : undefined;
    }

    /** @param {number|string} menuID */
    getMenuAsTree(menuID) {
        const menu = this.getMenu(menuID);
        if (!menu) {
            // menusData can be swapped by a reload/revalidation between the
            // caller capturing an id and this lookup (e.g. the command palette
            // holding a stale menu id); return nothing instead of throwing a
            // raw TypeError dialog.
            return;
        }
        if (!menu.childrenTree) {
            menu.childrenTree = menu.children.map((mid) => this.getMenuAsTree(mid));
        }
        return menu;
    }

    /**
     * The app whose (sub)menu tree runs the given action.
     *
     * Matches an action id OR an action path, because the URL may carry
     * either. When several menus point at the same action, ``preferredAppId``
     * breaks the tie — the caller passes the app the user was last in, so
     * reloading a shared action keeps them where they were.
     *
     * @param {number|string} action action id or action path
     * @param {number|string} [preferredAppId]
     * @returns {number|string|undefined} the ``appID``, if any
     */
    getAppIdByAction(action, preferredAppId) {
        if (!this._appByAction) {
            // One pass over the tree instead of one per lookup. Rebuilt on
            // every setData, so it can never outlive its menusData.
            this._appByAction = new Map();
            for (const menu of this.getAll()) {
                for (const key of [menu.actionID, menu.actionPath]) {
                    if (!key) {
                        continue;
                    }
                    let apps = this._appByAction.get(key);
                    if (!apps) {
                        apps = [];
                        this._appByAction.set(key, apps);
                    }
                    apps.push(menu.appID);
                }
            }
        }
        const apps = this._appByAction.get(action);
        if (!apps?.length) {
            return undefined;
        }
        return apps.includes(preferredAppId) ? preferredAppId : apps[0];
    }
}

/**
 * Service that loads, caches, and navigates the Odoo menu tree.
 *
 * Fetches menus from `/web/webclient/load_menus`, stores them in localStorage
 * for fast startup (see `menu_storage.js` for that trio's ordering rules), and
 * exposes methods to query apps, sub-menus, and trigger navigation via the
 * action service.
 */
export const menuService = {
    dependencies: ["action"],
    // selectMenu/reload are async: destroy-protection at useService("menu")
    // keeps a navbar/burger-menu/hotkey component from resuming into a
    // destroyed state if it unmounts mid-call.
    async: ["selectMenu", "reload"],
    async start(env) {
        // Serializes the async writers of the tree (boot-time background
        // revalidation vs. reload() vs. concurrent reload()s): each fetch
        // snapshots the counter and only commits if still the latest, so a slow
        // stale response can never overwrite fresher menus (nor persist its
        // stale hash, which would 304-pin the stale copy on next boots).
        let fetchGeneration = 0;

        const {
            menus: cachedMenus,
            raw: storedRaw,
            hash: storedHash,
        } = menuStorage.read();
        const tree = new MenuTree(cachedMenus || EMPTY_MENUS);

        if (cachedMenus) {
            // Warm boot: serve the cached copy now, revalidate in the
            // background.
            const generation = ++fetchGeneration;
            fetchMenus(false, storedHash)
                .then((res) => {
                    if (generation !== fetchGeneration) {
                        // A reload() committed fresher menus while this
                        // revalidation was in flight; drop this resolution.
                        return;
                    }
                    // res === null -> 304: cached copy confirmed up-to-date.
                    if (!res?.menus) {
                        return;
                    }
                    if (JSON.stringify(res.menus) !== storedRaw) {
                        menuStorage.write(res.menus, res.hash);
                        tree.setData(res.menus);
                        env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
                    } else if (res.hash && res.hash !== storedHash) {
                        // Same payload but hash changed (e.g. first boot after
                        // upgrading to the conditional-fetch server): persist so
                        // the next boot gets a 304.
                        menuStorage.write(res.menus, res.hash);
                    }
                })
                // Background revalidation only: stale menus are already on
                // screen, so a failed refetch isn't worth surfacing — but log
                // it so a persistent failure is diagnosable.
                .catch((error) => {
                    console.warn("Background menu revalidation failed", error);
                });
        } else {
            // Cold boot: no usable stored copy for this registry version.
            let res = await fetchMenus().catch(() => null);
            if (!res?.menus) {
                // The preload can resolve null on a 304 against a
                // stale/mismatched localStorage copy, which would leave the
                // tree empty and blank the webclient. Refetch unconditionally
                // (no cached hash -> never a 304).
                res = await fetchMenus(true).catch(() => null);
            }
            if (res?.menus) {
                tree.setData(res.menus);
                menuStorage.write(res.menus, res.hash);
            } else if (storedRaw) {
                // Last resort: a stale, version-mismatched copy beats a blank
                // client (a corrupt one falls through to the minimal root).
                tree.setData(menuStorage.parse(storedRaw) || EMPTY_MENUS);
            }
        }

        /** @param {Object|number} menu - menu descriptor or menu ID */
        function setCurrentMenu(menu) {
            menu = typeof menu === "number" ? tree.getMenu(menu) : menu;
            if (menu && menu.appID !== tree.currentAppId) {
                tree.currentAppId = menu.appID;
                browser.sessionStorage.setItem("menu_id", String(tree.currentAppId));
                env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
            }
        }

        return {
            getAll: () => tree.getAll(),
            getApps: () => tree.getApps(),
            getMenu: (menuId) => tree.getMenu(menuId),
            getCurrentApp: () => tree.getCurrentApp(),
            getMenuAsTree: (menuID) => tree.getMenuAsTree(menuID),
            getAppIdByAction: (action, preferredAppId) =>
                tree.getAppIdByAction(action, preferredAppId),
            setCurrentMenu,
            async selectMenu(menu) {
                menu = typeof menu === "number" ? tree.getMenu(menu) : menu;
                if (!menu || !menu.actionID) {
                    // The id may no longer resolve (the tree was swapped by a
                    // reload/revalidation while a stale id was held); bail out
                    // instead of throwing a raw TypeError.
                    return;
                }
                await env.services.action.doAction(menu.actionID, {
                    clearBreadcrumbs: true,
                    onActionReady: () => {
                        setCurrentMenu(menu);
                    },
                });
            },
            async reload() {
                // Explicit reload (e.g. after app install): skip the cached
                // hash, a change is expected, always take the full payload.
                const generation = ++fetchGeneration;
                const res = await fetchMenus(true);
                if (generation !== fetchGeneration) {
                    // Superseded by a newer fetch; it will commit and notify.
                    return;
                }
                if (res?.menus) {
                    tree.setData(res.menus);
                    // Persist so the next boot doesn't serve stale menus.
                    menuStorage.write(res.menus, res.hash);
                }
                env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
            },
        };
    },
};

registry.category("services").add("menu", menuService);
