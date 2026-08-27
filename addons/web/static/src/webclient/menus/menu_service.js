// @ts-check
/** @odoo-module native */

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
    /** @type {Map<number|string, (number|string)[]> | null} */
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
        return Object.hasOwn(this.menusData, menuId)
            ? this.menusData[menuId]
            : undefined;
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
        return preferredAppId !== undefined && apps.includes(preferredAppId)
            ? preferredAppId
            : apps[0];
    }
}

class MenuService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: any }} services
     */
    constructor(env, { action }) {
        this.env = env;
        this.action = action;
        this.fetchGeneration = 0;
        const {
            menus: cachedMenus,
            raw: storedRaw,
            hash: storedHash,
        } = menuStorage.read();
        this.cachedMenus = cachedMenus;
        this.storedRaw = storedRaw;
        this.storedHash = storedHash;
        this.tree = new MenuTree(cachedMenus || EMPTY_MENUS);
    }

    /**
     * @param {Object} menus
     * @param {string} [hash]
     */
    _persist(menus, hash) {
        menuStorage.write(menus, hash);
        this.storedRaw = JSON.stringify(menus);
        this.storedHash = hash;
    }

    async load() {
        if (this.cachedMenus) {
            const generation = ++this.fetchGeneration;
            fetchMenus(false, this.storedHash)
                .then((res) => {
                    if (generation !== this.fetchGeneration) {
                        return;
                    }
                    if (!res?.menus) {
                        return;
                    }
                    const changed = JSON.stringify(res.menus) !== this.storedRaw;
                    if (changed || (res.hash && res.hash !== this.storedHash)) {
                        this._persist(res.menus, res.hash);
                    }
                    if (changed) {
                        this.tree.setData(res.menus);
                        this.env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
                    }
                })
                .catch((error) => {
                    console.warn("Background menu revalidation failed", error);
                });
            return;
        }
        let res = await fetchMenus().catch(() => null);
        if (res === null) {
            res = await fetchMenus(true).catch(() => null);
        }
        if (res?.menus) {
            this.tree.setData(res.menus);
            this._persist(res.menus, res.hash);
        } else if (this.storedRaw) {
            this.tree.setData(menuStorage.parse(this.storedRaw) || EMPTY_MENUS);
        }
    }

    getAll() {
        return this.tree.getAll();
    }

    getApps() {
        return this.tree.getApps();
    }

    /**
     * @param {number|string} menuId
     */
    getMenu(menuId) {
        return this.tree.getMenu(menuId);
    }

    getCurrentApp() {
        return this.tree.getCurrentApp();
    }

    /** @param {number|string} menuID */
    getMenuAsTree(menuID) {
        return this.tree.getMenuAsTree(menuID);
    }

    /**
     * @param {any} action
     * @param {number|string} [preferredAppId]
     * @returns {number|string|undefined}
     */
    getAppIdByAction(action, preferredAppId) {
        return this.tree.getAppIdByAction(action, preferredAppId);
    }

    /** @param {Object|number} menu */
    setCurrentMenu(menu) {
        menu = typeof menu === "number" ? this.tree.getMenu(menu) : menu;
        if (menu && menu.appID !== this.tree.currentAppId) {
            this.tree.currentAppId = menu.appID;
            menuStorage.writeCurrentApp(menu.appID);
            this.env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
        }
    }

    /** @param {Object|number} menu */
    async selectMenu(menu) {
        menu = typeof menu === "number" ? this.tree.getMenu(menu) : menu;
        if (!menu || !menu.actionID) {
            return;
        }
        await this.action.doAction(menu.actionID, {
            clearBreadcrumbs: true,
            onActionReady: () => {
                this.setCurrentMenu(menu);
            },
        });
    }

    async reload() {
        const generation = ++this.fetchGeneration;
        const res = await fetchMenus(true);
        if (generation !== this.fetchGeneration) {
            return;
        }
        if (res?.menus) {
            this.tree.setData(res.menus);
            this._persist(res.menus, res.hash);
        }
        this.env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
    }
}

export const menuService = {
    dependencies: ["action"],
    async: ["selectMenu", "reload"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: any }} services
     * @returns {Promise<MenuService>}
     */
    async start(env, services) {
        const service = new MenuService(env, services);
        await service.load();
        return service;
    },
};

registry.category("services").add("menu", menuService);
