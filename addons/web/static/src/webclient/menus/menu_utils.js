// @ts-check
/** @odoo-module native */

import { normalize } from "@web/core/l10n/utils";

/**
 * @typedef {{childrenTree: MenuTreeNode[], actionPath?: string, actionID?: number | string, [key: string]: any}} MenuTreeNode
 */

/**
 * @param {MenuTreeNode} tree
 * @param {(node: MenuTreeNode, parents: MenuTreeNode[]) => void} cb
 * @param {MenuTreeNode[]} [parents]
 */
function traverseMenuTree(tree, cb, parents = []) {
    cb(tree, parents);
    tree.childrenTree.forEach((c) => traverseMenuTree(c, cb, [...parents, tree]));
}

/**
 * The url a menu entry navigates to. The action path is preferred over the id
 * so the url survives a database in which ids differ.
 *
 * @param {{ actionPath?: string, actionID?: number|string }} menu
 * @returns {string}
 */
export function menuHref(menu) {
    return `/odoo/${menu.actionPath || `action-${menu.actionID}`}`;
}

/**
 * @typedef MenuEntry
 * @property {string} parents the names of its ancestors, " / " joined
 * @property {string} label
 * @property {number} id
 * @property {string} [xmlid]
 * @property {number|string} [actionID]
 * @property {string} href
 * @property {number} [appID]
 * @property {string} [module] the app external ID namespace; legacy icon fallback
 * @property {string[]} [models] the models the app's menus open, for an app
 * @property {string} [category] the heading it sits under, for an app
 * @property {string[]} [keywords] the vocabulary its menu declares, for an app
 * @property {string[]} [searchTerms] what the app matches on besides its name
 * @property {string} [webIconData]
 * @property {{ iconClass: string, color: string, backgroundColor: string }} [webIcon]
 */

/**
 * An app: a menu whose id is its own appID. `computeAppsAndMenuItems` pushes
 * one only for a node carrying both an id and an action, and gives every one
 * of them an icon, so a launcher can read those fields off any app without
 * checking. `MenuEntry` alone does not say that, being the type of the deeper
 * menus too.
 *
 * @typedef {MenuEntry & {
 *  actionID: number|string,
 *  appID: number,
 *  href: string,
 *  id: number,
 *  label: string,
 *  parents: string,
 * }} AppEntry
 */

const MAX_APPS_PER_SEARCHABLE_MODEL = 1;

/**
 * What an app answers to besides its name: the keywords its menu declares
 * first, since they are the words a user actually types and a translator can
 * follow, then the addon that owns it, then the models only it opens.
 *
 * @param {AppEntry} app
 * @param {Map<string, number>} appsByModel how many apps each model reaches
 * @returns {string[]}
 */
function appSearchTerms(app, appsByModel) {
    const terms = [...(app.keywords || [])];
    if (app.module) {
        terms.push(app.module);
    }
    for (const model of app.models || []) {
        if ((appsByModel.get(model) || 0) <= MAX_APPS_PER_SEARCHABLE_MODEL) {
            terms.push(model);
        }
    }
    return terms;
}

/**
 * @param {Object} menuTree
 * @returns {{ apps: AppEntry[], menuItems: MenuEntry[] }}
 */
export function computeAppsAndMenuItems(menuTree) {
    /** @type {AppEntry[]} */
    const apps = [];
    /** @type {MenuEntry[]} */
    const menuItems = [];
    /** @type {Map<number, Set<string>>} */
    const modelsByApp = new Map();
    /** @type {Map<string, number>} */
    const appsByModel = new Map();
    traverseMenuTree(/** @type {MenuTreeNode} */ (menuTree), (menuItem, parents) => {
        if (menuItem.actionResModel && menuItem.appID) {
            let models = modelsByApp.get(menuItem.appID);
            if (!models) {
                models = new Set();
                modelsByApp.set(menuItem.appID, models);
            }
            if (!models.has(menuItem.actionResModel)) {
                models.add(menuItem.actionResModel);
                appsByModel.set(
                    menuItem.actionResModel,
                    (appsByModel.get(menuItem.actionResModel) || 0) + 1,
                );
            }
        }
        if (!menuItem.id || !menuItem.actionID) {
            return;
        }
        const isApp = menuItem.id === menuItem.appID;
        /** @type {AppEntry} */
        const item = {
            parents: parents
                .slice(1)
                .map((p) => p.name)
                .join(" / "),
            label: menuItem.name,
            id: menuItem.id,
            xmlid: menuItem.xmlid,
            actionID: menuItem.actionID,
            href: menuHref(menuItem),
            appID: menuItem.appID,
        };
        if (!isApp) {
            menuItems.push(item);
            return;
        }
        const iconParts =
            typeof menuItem.webIcon === "string" ? menuItem.webIcon.split(",") : [];
        const module =
            typeof menuItem.xmlid === "string" && menuItem.xmlid.includes(".")
                ? menuItem.xmlid.split(".")[0]
                : undefined;
        if (module || (iconParts.length === 2 && iconParts[0])) {
            item.module = module || iconParts[0];
        }
        if (menuItem.webCategory) {
            item.category = menuItem.webCategory;
        }
        if (menuItem.webKeywords) {
            item.keywords = menuItem.webKeywords
                .split(",")
                .map((/** @type {string} */ word) => word.trim())
                .filter(Boolean);
        }
        if (menuItem.webIconData) {
            item.webIconData = menuItem.webIconData;
        } else {
            const [iconClass, color, backgroundColor] = (menuItem.webIcon || "").split(
                ",",
            );
            if (backgroundColor !== undefined) {
                item.webIcon = { iconClass, color, backgroundColor };
            } else {
                item.webIconData = "/web/static/img/default_icon_app.png";
            }
        }
        apps.push(item);
    });
    for (const app of apps) {
        app.models = [...(modelsByApp.get(/** @type {number} */ (app.appID)) || [])];
        app.searchTerms = appSearchTerms(app, appsByModel);
    }
    return { apps, menuItems };
}

/** @type {WeakMap<Object, { apps: AppEntry[], menuItems: MenuEntry[] }>} */
const flattenedTrees = new WeakMap();

/**
 * @param {Object} menuTree
 * @returns {{ apps: AppEntry[], menuItems: MenuEntry[] }}
 */
export function flattenMenuTree(menuTree) {
    let flattened = flattenedTrees.get(menuTree);
    if (!flattened) {
        flattened = computeAppsAndMenuItems(menuTree);
        flattenedTrees.set(menuTree, flattened);
    }
    return flattened;
}

/** @type {WeakMap<object, string>} */
const searchKeys = new WeakMap();

/**
 * What a menu entry is matched against: its own name first and its ancestors
 * behind it, so "quotations" ranks "Sales / Orders / Quotations" above a menu
 * named after its app. Normalized once here and searched `preNormalized`, so
 * a keystroke re-normalizes nothing: normalizing is two Unicode passes and a
 * regex per string, and a query runs over every menu in the database.
 *
 * @param {{ parents: string, label: string }} menu the two fields it reads,
 *  rather than a whole `MenuEntry`, which is more than it needs
 * @returns {string}
 */
export function menuSearchKey(menu) {
    let key = searchKeys.get(menu);
    if (key === undefined) {
        key = normalize(
            `${menu.parents} / ${menu.label}`.split("/").reverse().join("/"),
        );
        searchKeys.set(menu, key);
    }
    return key;
}

/** @type {WeakMap<object, string[]>} */
const appSearchKeys = new WeakMap();

/**
 * What an app is matched against: its name and everything `appSearchTerms`
 * gathered, each normalized once and searched `preNormalized`, the way
 * `menuSearchKey` is. `fuzzyLookup` scores a list of strings by its best
 * member, so a name match still outranks a model match on the same query.
 *
 * @param {{ label: string, searchTerms?: string[] }} app
 * @returns {string[]}
 */
export function appSearchKey(app) {
    let keys = appSearchKeys.get(app);
    if (keys === undefined) {
        keys = [app.label, ...(app.searchTerms || [])].map(normalize);
        appSearchKeys.set(app, keys);
    }
    return keys;
}

/**
 * Sorts in place, by the stored order of the xmlids. Anything carrying an
 * xmlid will do: this reads nothing else off an app.
 *
 * @param {{ xmlid?: string }[]} apps
 * @param {string[]} order
 */
export function reorderApps(apps, order) {
    apps.sort((a, b) => {
        const aIndex = a.xmlid === undefined ? -1 : order.indexOf(a.xmlid);
        const bIndex = b.xmlid === undefined ? -1 : order.indexOf(b.xmlid);
        if (aIndex === -1 && bIndex === -1) {
            return 0;
        }
        if (aIndex === -1) {
            return -1;
        }
        if (bIndex === -1) {
            return 1;
        }
        return aIndex - bIndex;
    });
}

export const HOME_MENU_CONFIG_VERSION = 2;

/**
 * The user's home menu layout, as stored in `res.users.settings.homemenu_config`.
 * Version 1 was the bare `order` list; anything unreadable is the default layout.
 *
 * @typedef HomeMenuConfig
 * @property {string[]} order xmlids, the drag-and-drop order
 * @property {string[]} pinned xmlids shown first, in this order
 * @property {string[]} hidden xmlids kept out of the grid, still searchable
 */

/** @param {unknown} list */
function xmlids(list) {
    return Array.isArray(list)
        ? [...new Set(list.filter((item) => typeof item === "string" && item))]
        : [];
}

/**
 * @param {unknown} raw the stored value, a JSON string or already parsed
 * @returns {HomeMenuConfig | null}
 */
export function readHomeMenuConfig(raw) {
    let value = raw;
    if (typeof raw === "string") {
        try {
            value = JSON.parse(raw);
        } catch {
            value = null;
        }
    }
    if (Array.isArray(value)) {
        return { order: xmlids(value), pinned: [], hidden: [] };
    }
    if (
        value &&
        typeof value === "object" &&
        (!Object.hasOwn(value, "version") ||
            /** @type {Record<string, unknown>} */ (value).version ===
                HOME_MENU_CONFIG_VERSION)
    ) {
        const config = /** @type {Record<string, unknown>} */ (value);
        return {
            order: xmlids(config.order),
            pinned: xmlids(config.pinned).filter(
                (id) => !xmlids(config.hidden).includes(id),
            ),
            hidden: xmlids(config.hidden),
        };
    }
    return null;
}

/** @param {unknown} raw @returns {HomeMenuConfig} */
export function parseHomeMenuConfig(raw) {
    return readHomeMenuConfig(raw) ?? { order: [], pinned: [], hidden: [] };
}

/**
 * @param {HomeMenuConfig} config
 * @returns {string}
 */
export function serializeHomeMenuConfig(config) {
    return JSON.stringify({
        version: HOME_MENU_CONFIG_VERSION,
        order: [...config.order],
        pinned: [...config.pinned],
        hidden: [...config.hidden],
    });
}

/**
 * @param {HomeMenuConfig} config
 * @returns {boolean}
 */
export function isDefaultHomeMenuConfig(config) {
    return !config.order.length && !config.pinned.length && !config.hidden.length;
}
