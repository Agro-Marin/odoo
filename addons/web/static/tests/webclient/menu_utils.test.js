// @ts-check

import { expect, test } from "@odoo/hoot";
import { computeAppsAndMenuItems, reorderApps } from "@web/webclient/menus/menu_utils";

/** @param {string[]} xmlids */
function makeApps(xmlids) {
    return xmlids.map((xmlid) => ({ xmlid }));
}

/** @param {{xmlid: string}[]} apps */
function xmlids(apps) {
    return apps.map((a) => a.xmlid);
}

test("reorderApps sorts apps by the given custom order", () => {
    const apps = makeApps(["a", "b", "c"]);
    reorderApps(apps, ["c", "a", "b"]);
    expect(xmlids(apps)).toEqual(["c", "a", "b"]);
});

test("reorderApps keeps the original relative order of apps absent from the order", () => {
    const apps = makeApps(["a", "b", "c", "d"]);
    reorderApps(apps, ["d", "b"]);
    expect(xmlids(apps)).toEqual(["a", "c", "d", "b"]);
});

test("reorderApps: a newly installed app does not scramble the customized order", () => {
    const apps = makeApps(["e1", "e2", "e3", "new"]);
    reorderApps(apps, ["e3", "e1", "e2"]);
    expect(xmlids(apps)).toEqual(["new", "e3", "e1", "e2"]);
});

/**
 * @param {Object} spec
 */
function makeTree(spec) {
    const build = (node, appID) => {
        const id = node.id;
        const ownAppID = appID ?? id;
        return {
            id,
            name: node.name,
            xmlid: node.xmlid,
            appID: ownAppID,
            actionID: node.actionID,
            actionPath: node.actionPath,
            webIcon: node.webIcon,
            webIconData: node.webIconData,
            childrenTree: (node.children || []).map((c) =>
                build(c, id === ownAppID && appID === undefined ? id : ownAppID),
            ),
        };
    };
    return {
        id: "root",
        name: "root",
        appID: "root",
        childrenTree: spec.map((app) => build(app, undefined)),
    };
}

test("computeAppsAndMenuItems splits apps from their descendants", () => {
    const tree = makeTree([
        {
            id: 1,
            name: "Sales",
            xmlid: "sale.menu_root",
            actionID: 10,
            webIconData: "data:image/png;base64,AAA",
            children: [
                { id: 2, name: "Orders", actionID: 11 },
                { id: 3, name: "Products", actionID: 12 },
            ],
        },
    ]);
    const { apps, menuItems } = computeAppsAndMenuItems(tree);
    expect(apps.map((a) => a.label)).toEqual(["Sales"]);
    expect(menuItems.map((m) => m.label)).toEqual(["Orders", "Products"]);
    expect(apps[0].webIconData).toBe("data:image/png;base64,AAA");
});

test("computeAppsAndMenuItems records the ancestor path and the owning app", () => {
    const tree = makeTree([
        {
            id: 1,
            name: "Sales",
            actionID: 10,
            children: [
                {
                    id: 2,
                    name: "Configuration",
                    actionID: 11,
                    children: [{ id: 3, name: "Tags", actionID: 12 }],
                },
            ],
        },
    ]);
    const { menuItems } = computeAppsAndMenuItems(tree);
    const tags = menuItems.find((m) => m.label === "Tags");
    expect(tags.parents).toBe("Sales / Configuration");
    expect(tags.appID).toBe(1);
});

test("computeAppsAndMenuItems skips nodes without an action", () => {
    const tree = makeTree([
        {
            id: 1,
            name: "Sales",
            actionID: 10,
            children: [{ id: 2, name: "No action" }],
        },
    ]);
    const { apps, menuItems } = computeAppsAndMenuItems(tree);
    expect(apps).toHaveLength(1);
    expect(menuItems).toEqual([]);
});

test("computeAppsAndMenuItems parses webIcon and falls back to the default", () => {
    const tree = makeTree([
        { id: 1, name: "Styled", actionID: 10, webIcon: "fa-cog,#fff,#000" },
        { id: 2, name: "Bare", actionID: 20, webIcon: "fa-cog" },
        { id: 3, name: "None", actionID: 30 },
    ]);
    const { apps } = computeAppsAndMenuItems(tree);
    expect(apps[0].webIcon).toEqual({
        iconClass: "fa-cog",
        color: "#fff",
        backgroundColor: "#000",
    });
    expect(apps[1].webIconData).toBe("/web/static/img/default_icon_app.png");
    expect(apps[2].webIconData).toBe("/web/static/img/default_icon_app.png");
});

test("computeAppsAndMenuItems builds hrefs from the action path when present", () => {
    const tree = makeTree([
        {
            id: 1,
            name: "Sales",
            actionID: 10,
            actionPath: "sales",
            children: [{ id: 2, name: "Orders", actionID: 11 }],
        },
    ]);
    const { apps, menuItems } = computeAppsAndMenuItems(tree);
    expect(apps[0].href).toBe("/odoo/sales");
    expect(menuItems[0].href).toBe("/odoo/action-11");
});

test("computeAppsAndMenuItems handles a subtree that is not rooted at root", () => {
    const app = makeTree([
        {
            id: 1,
            name: "Sales",
            actionID: 10,
            children: [{ id: 2, name: "Orders", actionID: 11 }],
        },
    ]).childrenTree[0];
    const { apps, menuItems } = computeAppsAndMenuItems(app);
    expect(apps.map((a) => a.label)).toEqual(["Sales"]);
    expect(menuItems.map((m) => m.label)).toEqual(["Orders"]);
});
