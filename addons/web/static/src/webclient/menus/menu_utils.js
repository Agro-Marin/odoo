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
 * @param {Object} menuTree
 * @returns {Object}
 */
export function computeAppsAndMenuItems(menuTree) {
    const apps = [];
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
            href: `/odoo/${menuItem.actionPath || `action-${menuItem.actionID}`}`,
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
 * @param {Object[]} apps
 * @param {string[]} order
 */
export function reorderApps(apps, order) {
    apps.sort((a, b) => {
        const aIndex = order.indexOf(a.xmlid);
        const bIndex = order.indexOf(b.xmlid);
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
