// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    computeAppsAndMenuItems,
    isDefaultHomeMenuConfig,
    parseHomeMenuConfig,
    reorderApps,
    serializeHomeMenuConfig,
} from "@web/webclient/menus/menu_utils";

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
    // `find` may come back empty; saying so keeps a missing item an assertion
    // failure instead of a TypeError.
    expect(tags?.parents).toBe("Sales / Configuration");
    expect(tags?.appID).toBe(1);
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

test("parseHomeMenuConfig reads the version-1 bare order list", () => {
    expect(parseHomeMenuConfig('["app.b","app.a"]')).toEqual({
        order: ["app.b", "app.a"],
        pinned: [],
        hidden: [],
    });
    expect(parseHomeMenuConfig(["app.a"])).toEqual({
        order: ["app.a"],
        pinned: [],
        hidden: [],
    });
});

test("parseHomeMenuConfig reads the versioned object and drops what is not an xmlid", () => {
    expect(
        parseHomeMenuConfig(
            '{"version":2,"order":["app.a",3],"pinned":["app.b"],"hidden":null}',
        ),
    ).toEqual({ order: ["app.a"], pinned: ["app.b"], hidden: [] });
});

test("parseHomeMenuConfig treats nothing and garbage as the default layout", () => {
    for (const raw of [undefined, null, "", "null", "{", 42, "[1,2]"]) {
        const config = parseHomeMenuConfig(raw);
        expect(config).toEqual({ order: [], pinned: [], hidden: [] });
        expect(isDefaultHomeMenuConfig(config)).toBe(true);
    }
});

test("serializeHomeMenuConfig round-trips through parseHomeMenuConfig", () => {
    const config = { order: ["app.b", "app.a"], pinned: ["app.a"], hidden: ["app.c"] };
    const raw = serializeHomeMenuConfig(config);
    expect(JSON.parse(raw).version).toBe(2);
    expect(parseHomeMenuConfig(raw)).toEqual(config);
    expect(isDefaultHomeMenuConfig(config)).toBe(false);
});

test("computeAppsAndMenuItems names the addon an app's icon comes from", () => {
    const tree = {
        id: "root",
        name: "root",
        appID: "root",
        childrenTree: [
            {
                id: 1,
                name: "CRM",
                appID: 1,
                actionID: 10,
                webIcon: "crm,static/description/icon.png",
                webIconData: "data:image/png;base64,AAA",
                childrenTree: [],
            },
            {
                id: 2,
                name: "Studio App",
                appID: 2,
                actionID: 20,
                webIcon: "fa fa-leaf,#fff,#123456",
                childrenTree: [],
            },
        ],
    };
    const { apps } = computeAppsAndMenuItems(tree);
    expect(apps[0].module).toBe("crm");
    expect(apps[1].module).toBe(undefined);
});
