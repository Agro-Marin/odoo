// @ts-check
/** @odoo-module native */

/**
 * @param {Object} tree
 * @param {Function} cb
 * @param {Object[]} [parents]
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
 * One entry of the app grid or of the command palette's menu list, as built
 * from a menu tree node.
 *
 * @typedef MenuEntry
 * @property {string} parents the names of its ancestors, " / " joined
 * @property {string} label
 * @property {number} id
 * @property {string} [xmlid]
 * @property {number|string} [actionID]
 * @property {string} href
 * @property {number} [appID]
 * @property {string} [module] the addon whose icon the app carries, for an app
 * @property {string} [webIconData]
 * @property {{ iconClass: string, color: string, backgroundColor: string }} [webIcon]
 */

/**
 * @param {Object} menuTree
 * @returns {{ apps: MenuEntry[], menuItems: MenuEntry[] }}
 */
export function computeAppsAndMenuItems(menuTree) {
    /** @type {MenuEntry[]} */
    const apps = [];
    /** @type {MenuEntry[]} */
    const menuItems = [];
    traverseMenuTree(menuTree, (menuItem, parents) => {
        if (!menuItem.id || !menuItem.actionID) {
            return;
        }
        const isApp = menuItem.id === menuItem.appID;
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
        // "module,static/description/icon.png" names the addon; the three-part
        // "iconClass,color,background" form of a Studio icon names none.
        const iconParts =
            typeof menuItem.webIcon === "string" ? menuItem.webIcon.split(",") : [];
        if (iconParts.length === 2 && iconParts[0]) {
            item.module = iconParts[0];
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
    return { apps, menuItems };
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
        // An entry with no xmlid is not in a stored order and sorts as such,
        // which is what indexOf already returned for it.
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
    return Array.isArray(list) ? list.filter((item) => typeof item === "string") : [];
}

/**
 * @param {unknown} raw the stored value, a JSON string or already parsed
 * @returns {HomeMenuConfig}
 */
export function parseHomeMenuConfig(raw) {
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
    if (value && typeof value === "object") {
        const config = /** @type {Record<string, unknown>} */ (value);
        return {
            order: xmlids(config.order),
            pinned: xmlids(config.pinned),
            hidden: xmlids(config.hidden),
        };
    }
    return { order: [], pinned: [], hidden: [] };
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
