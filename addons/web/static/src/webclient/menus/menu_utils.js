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
