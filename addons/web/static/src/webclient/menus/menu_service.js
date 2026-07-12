// @ts-check
/** @odoo-module native */

/** @module @web/webclient/menus/menu_service - Service that loads, caches, and navigates the Odoo menu tree */

import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

const loadMenusUrl = `/web/webclient/load_menus`;

/**
 * Service that loads, caches, and navigates the Odoo menu tree.
 *
 * Fetches menus from `/web/webclient/load_menus`, stores them in localStorage
 * for fast startup, and exposes methods to query apps, sub-menus, and trigger
 * navigation via the action service.
 */
export const menuService = {
    dependencies: ["action"],
    // selectMenu/reload are async: destroy-protection at useService("menu")
    // keeps a navbar/burger-menu/hotkey component from resuming into a
    // destroyed state if it unmounts mid-call.
    async: ["selectMenu", "reload"],
    async start(env) {
        let currentAppId;
        let menusData;
        // Serializes the async writers of `menusData` (boot-time background
        // revalidation vs. reload() vs. concurrent reload()s): each fetch
        // snapshots the counter and only commits if still the latest, so a
        // slow stale response can never overwrite fresher menus (nor persist
        // its stale hash, which would 304-pin the stale copy on next boots).
        let fetchGeneration = 0;

        /**
         * Fetch the menu tree from the server.
         *
         * Conditional-fetch contract: when ``cachedHash`` (the value of the
         * ``X-Menus-Hash`` header persisted alongside the localStorage copy)
         * is passed, the server answers an empty ``304`` if the payload is
         * unchanged — resolved here as ``null`` — instead of re-sending the
         * full payload (base64 app icons included) on every boot.
         *
         * @param {boolean} [reload]
         * @param {string} [cachedHash]
         * @returns {Promise<{menus: Object, hash?: string} | null>} the menus
         *  and their server-side hash, or ``null`` when the cached copy is
         *  confirmed up-to-date (304)
         */
        const fetchMenus = async (reload, cachedHash) => {
            if (!reload && /** @type {any} */ (odoo).loadMenusPromise) {
                // Parse-time preload from web.webclient_bootstrap: already
                // normalized to the same `{menus, hash} | null` shape (and
                // already carries the stored hash when it was valid).
                return /** @type {any} */ (odoo).loadMenusPromise;
            }
            const url = cachedHash
                ? `${loadMenusUrl}?hash=${encodeURIComponent(cachedHash)}`
                : loadMenusUrl;
            const res = await browser.fetch(url, {
                cache: "no-store",
            });
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
        };
        /**
         * @param {Object} data
         * @param {string} [hash] server-side hash of ``data`` (``X-Menus-Hash``)
         */
        const persistMenus = (data, hash) => {
            try {
                browser.localStorage.setItem("webclient_menus", JSON.stringify(data));
                if (hash) {
                    browser.localStorage.setItem("webclient_menus_hash", hash);
                } else if (
                    browser.localStorage.getItem("webclient_menus_hash") !== null
                ) {
                    // No hash (e.g. mocked route): drop any stale one so the next
                    // boot fetches the full payload. Only touch storage when a
                    // hash was actually stored, to avoid a spurious removeItem
                    // in tests that spy on localStorage.
                    browser.localStorage.removeItem("webclient_menus_hash");
                }
                // Version LAST: it gates reuse of the payload on the next boot.
                // Writing it first meant a quota failure on the payload write
                // left a current version stamp over a stale payload.
                browser.localStorage.setItem(
                    "webclient_menus_version",
                    session.registry_hash,
                );
            } catch (error) {
                console.error("Error while storing menus in localStorage", error);
                try {
                    // Close the gate: a partially-written trio must not be
                    // reused on the next boot.
                    browser.localStorage.removeItem("webclient_menus_version");
                } catch {
                    // Storage fully unavailable: nothing to clean up.
                }
            }
        };
        /**
         * Parse a stored menu payload, discarding the whole cached trio when
         * it is corrupt (interrupted write, extension, manual edit): before
         * this guard, one corrupt value made ``start()`` throw on EVERY
         * subsequent boot — a permanently blank webclient until the user
         * manually cleared storage.
         *
         * @param {string} raw
         * @returns {Object|null} the parsed menus, or null when corrupt
         */
        const parseStoredMenus = (raw) => {
            try {
                return JSON.parse(raw);
            } catch {
                console.warn(
                    "Corrupt webclient_menus in localStorage; discarding the cached copy",
                );
                try {
                    browser.localStorage.removeItem("webclient_menus");
                    browser.localStorage.removeItem("webclient_menus_version");
                    browser.localStorage.removeItem("webclient_menus_hash");
                } catch {
                    // Storage unavailable: nothing to clean up.
                }
                return null;
            }
        };
        const storedMenus = browser.localStorage.getItem("webclient_menus");
        const storedMenusVersion = browser.localStorage.getItem(
            "webclient_menus_version",
        );
        const storedMenusHash =
            browser.localStorage.getItem("webclient_menus_hash") || undefined;

        const cachedMenus =
            storedMenus && storedMenusVersion === session.registry_hash
                ? parseStoredMenus(storedMenus)
                : null;
        if (cachedMenus) {
            const generation = ++fetchGeneration;
            fetchMenus(false, storedMenusHash)
                .then((res) => {
                    if (generation !== fetchGeneration) {
                        // A reload() committed fresher menus while this
                        // revalidation was in flight; drop this resolution.
                        return;
                    }
                    // res === null → 304: cached copy confirmed up-to-date.
                    if (res && res.menus) {
                        const fetchedMenus = JSON.stringify(res.menus);
                        if (fetchedMenus !== storedMenus) {
                            persistMenus(res.menus, res.hash);
                            menusData = res.menus;
                            env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
                        } else if (res.hash && res.hash !== storedMenusHash) {
                            // Same payload but hash changed (e.g. first boot after
                            // upgrading to the conditional-fetch server): persist
                            // so the next boot gets a 304.
                            persistMenus(res.menus, res.hash);
                        }
                    }
                })
                // Background revalidation only: stale menus are already on
                // screen, so a failed refetch isn't worth surfacing — but log
                // it so a persistent failure is diagnosable.
                .catch((error) => {
                    console.warn("Background menu revalidation failed", error);
                });
            menusData = cachedMenus;
        } else {
            // Cold boot: no usable stored copy for this registry version.
            let res;
            try {
                res = await fetchMenus();
            } catch {
                // Parse-time preload rejected: treat as unusable.
                res = null;
            }
            if (!res || !res.menus) {
                // The preload can resolve null on a 304 against a stale/mismatched
                // localStorage copy, leaving menusData undefined and blanking the
                // webclient. Refetch unconditionally (no cached hash → never a 304).
                try {
                    res = await fetchMenus(true);
                } catch {
                    res = null;
                }
            }
            if (res && res.menus) {
                menusData = res.menus;
                persistMenus(res.menus, res.hash);
            } else if (storedMenus) {
                // Last resort: a stale, version-mismatched copy beats a blank
                // client (a corrupt one falls through to the minimal root).
                menusData = parseStoredMenus(storedMenus);
            }
        }
        if (!menusData) {
            // Total failure (fetch failed, no stored copy): a minimal root
            // beats an exception on the first getAll()/getApps() call and a
            // blanked webclient with an opaque error.
            menusData = {
                root: { id: "root", children: [], name: "root", appID: "root" },
            };
        }

        /** @param {number|string} menuId */
        function _getMenu(menuId) {
            return menusData[menuId];
        }
        /** @param {Object|number} menu - menu descriptor or menu ID */
        function setCurrentMenu(menu) {
            menu = typeof menu === "number" ? _getMenu(menu) : menu;
            if (menu && menu.appID !== currentAppId) {
                currentAppId = menu.appID;
                browser.sessionStorage.setItem("menu_id", currentAppId);
                env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
            }
        }

        return {
            getAll() {
                return Object.values(menusData);
            },
            getApps() {
                return this.getMenu("root").children.map((mid) => this.getMenu(mid));
            },
            getMenu: _getMenu,
            getCurrentApp() {
                if (!currentAppId) {
                    return;
                }
                return this.getMenu(currentAppId);
            },
            getMenuAsTree(menuID) {
                const menu = this.getMenu(menuID);
                if (!menu.childrenTree) {
                    menu.childrenTree = menu.children.map((mid) =>
                        this.getMenuAsTree(mid),
                    );
                }
                return menu;
            },
            async selectMenu(menu) {
                menu = typeof menu === "number" ? this.getMenu(menu) : menu;
                if (!menu.actionID) {
                    return;
                }
                await env.services.action.doAction(menu.actionID, {
                    clearBreadcrumbs: true,
                    onActionReady: () => {
                        setCurrentMenu(menu);
                    },
                });
            },
            setCurrentMenu,
            async reload() {
                // Explicit reload (e.g. after app install): skip the cached hash,
                // a change is expected, always take the full payload.
                const generation = ++fetchGeneration;
                const res = await fetchMenus(true);
                if (generation !== fetchGeneration) {
                    // Superseded by a newer fetch; it will commit and notify.
                    return;
                }
                if (res && res.menus) {
                    menusData = res.menus;
                    // Persist so the next boot doesn't serve stale menus from localStorage.
                    persistMenus(res.menus, res.hash);
                }
                env.bus.trigger(AppEvent.MENUS_APP_CHANGED);
            },
        };
    },
};

registry.category("services").add("menu", menuService);
