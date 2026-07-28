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
 * change, and a full scan of ``getAll()`` per change does not scale.
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
    async: ["selectMenu", "reload"],
    async start(env) {
        let fetchGeneration = 0;

        const {
            menus: cachedMenus,
            raw: storedRaw,
            hash: storedHash,
        } = menuStorage.read();
        const tree = new MenuTree(cachedMenus || EMPTY_MENUS);

        if (cachedMenus) {
            const generation = ++fetchGeneration;
            fetchMenus(false, storedHash)
                .then((res) => {
                    if (generation !== fetchGeneration) {
                        return;
                    }
                    if (!res?.menus) {
                        return;
                    }
                    if (JSON.stringify(res.menus) !== storedRaw) {
                        menuStorage.write(res.menus, res.hash);
                        tree.setData(res.menus);
                        env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
                    } else if (res.hash && res.hash !== storedHash) {
                        menuStorage.write(res.menus, res.hash);
                    }
                })
                .catch((error) => {
                    console.warn("Background menu revalidation failed", error);
                });
        } else {
            let res = await fetchMenus().catch(() => null);
            if (!res?.menus) {
                res = await fetchMenus(true).catch(() => null);
            }
            if (res?.menus) {
                tree.setData(res.menus);
                menuStorage.write(res.menus, res.hash);
            } else if (storedRaw) {
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
                const generation = ++fetchGeneration;
                const res = await fetchMenus(true);
                if (generation !== fetchGeneration) {
                    return;
                }
                if (res?.menus) {
                    tree.setData(res.menus);
                    menuStorage.write(res.menus, res.hash);
                }
                env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
            },
        };
    },
};

registry.category("services").add("menu", menuService);
