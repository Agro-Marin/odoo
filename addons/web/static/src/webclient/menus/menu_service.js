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

/**
 * The `menu` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * **The async bootstrap moved into the class, not into `start()`.** `start` is
 * `async` here, and the obvious split — fetch in `start`, then construct —
 * would have separated the bootstrap from `reload()`, which shares
 * `fetchGeneration` with it: both bump it and then check whether they are still
 * the newest request before writing. Splitting them would have left the
 * background revalidation racing a `reload()` with no shared counter to arbitrate.
 * So `start()` constructs and awaits `load()`, and the counter stays one field.
 */
export class MenuService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: any }} services
     */
    constructor(env, { action }) {
        this.env = env;
        // Injected, not reached through `env.services.action`. The service has
        // always declared `dependencies: ["action"]`; taking it from the
        // injection point is what that declaration is for, and it is the
        // difference between a dependency and an ambient lookup.
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
     * Fills the tree: from cache plus a background revalidation when there is a
     * usable cached copy, otherwise by fetching before the client boots.
     */
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
                    if (JSON.stringify(res.menus) !== this.storedRaw) {
                        menuStorage.write(res.menus, res.hash);
                        this.tree.setData(res.menus);
                        this.env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
                    } else if (res.hash && res.hash !== this.storedHash) {
                        menuStorage.write(res.menus, res.hash);
                    }
                })
                .catch((error) => {
                    console.warn("Background menu revalidation failed", error);
                });
            return;
        }
        let res = await fetchMenus().catch(() => null);
        // `undefined` is the parse-time opt-out: the PoS UI, the documents
        // portal and project sharing all set `loadMenusPromise` to a
        // promise of nothing to say this page has no menus to load. `null`
        // is a 304 or an outright failure, and with no usable cached copy
        // that has to be refetched or the client boots blank. Both are
        // falsy, so asking `!res?.menus` sent the opted-out pages a
        // request they had explicitly declined.
        if (res === null) {
            res = await fetchMenus(true).catch(() => null);
        }
        if (res?.menus) {
            this.tree.setData(res.menus);
            menuStorage.write(res.menus, res.hash);
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
     * Mirrors `MenuTree.getMenu`'s own `{number|string}`: the tree accepts the
     * string ids the fixtures use ("root"), and narrowing this to `number`
     * would be precision the implementation does not have.
     *
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
     * `action` is `any` for parity with the closure this replaced, whose params
     * were untyped. Mirroring `MenuTree.getAppIdByAction`'s own
     * `{number|string}` would be *better*, and surfaces exactly one real
     * mismatch — `webclient.js:86` passes
     * `router.current.actionStack?.[0]?.action`, which is wider than that. Left
     * as a separate fix rather than widening this conversion's blast radius
     * into a file it does not otherwise touch.
     *
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
                // Routed through `this` so a downstream patch of
                // `setCurrentMenu` applies to this caller too.
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
            menuStorage.write(res.menus, res.hash);
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
