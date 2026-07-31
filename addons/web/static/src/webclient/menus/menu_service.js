// @ts-check
/** @odoo-module native */

/** @module @web/webclient/menus/menu_service */

import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";

import { menuStorage } from "./menu_storage.js";

const loadMenusUrl = `/web/webclient/load_menus`;

const EMPTY_MENUS = {
    root: { id: "root", children: [], name: "root", appID: "root" },
};

/**
 * @param {boolean} [reload]
 * @param {string} [cachedHash]
 * @returns {Promise<{menus: Object, hash?: string} | null>}
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

class MenuTree {
    /** @type {Object} */
    menusData;
    /** @type {Map<number|string, Object> | null} */
    _appByAction = null;
    /** @type {Map<number|string, Object>} */
    _treeByMenuId = new Map();

    /** @param {Object} menusData */
    constructor(menusData) {
        this.setData(menusData);
        /** @type {number | string | undefined} */
        this.currentAppId = undefined;
    }

    /**
     * @param {Object} [menusData]
     */
    setData(menusData) {
        if (menusData && !menusData.root) {
            console.warn("Discarding a menu payload with no root entry");
        }
        this.menusData = menusData?.root ? menusData : EMPTY_MENUS;
        this._appByAction = null;
        this._treeByMenuId = new Map();
    }

    /** @param {number|string} menuId */
    getMenu(menuId) {
        return this.menusData[menuId];
    }

    getAll() {
        return Object.values(this.menusData);
    }

    getApps() {
        return this._resolveChildren(this.getMenu("root"));
    }

    /**
     * @param {Object} [menu]
     * @returns {Object[]}
     */
    _resolveChildren(menu) {
        return (menu?.children || []).map((mid) => this.getMenu(mid)).filter(Boolean);
    }

    getCurrentApp() {
        return this.currentAppId ? this.getMenu(this.currentAppId) : undefined;
    }

    /**
     * The resolved tree is memoized per menu id rather than written back onto
     * the payload: `setData` would otherwise have to scrub a `childrenTree`
     * left on menus it reuses, and consumers would see the cache as data.
     *
     * @param {number|string} menuID
     */
    getMenuAsTree(menuID) {
        const menu = this.getMenu(menuID);
        if (!menu) {
            return;
        }
        let tree = this._treeByMenuId.get(menuID);
        if (!tree) {
            tree = { ...menu, childrenTree: [] };
            this._treeByMenuId.set(menuID, tree);
            tree.childrenTree = this._resolveChildren(menu)
                .map((child) => this.getMenuAsTree(child.id))
                .filter(Boolean);
        }
        return tree;
    }

    /**
     * @param {number|string} action
     * @param {number|string} [preferredAppId]
     * @returns {number|string|undefined}
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

        /** @param {Object|number} menu */
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
