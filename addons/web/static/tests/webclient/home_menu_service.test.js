import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { Deferred } from "@odoo/hoot-mock";
import { defineMenus, mountWebClient, onRpc } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { WebClient } from "@web/webclient/webclient";

test("use stored menus, and update on load_menus return", async () => {
    const def = new Deferred();
    onRpc("/web/webclient/load_menus", () => def);
    defineMenus([
        {
            id: 1,
            appID: 1,
            actionID: 1,
            xmlid: "",
            name: "Partners",
            children: [],
            webIconData: "",
            webIcon: "bloop,bloop",
        },
        {
            id: 2,
            appID: 2,
            actionID: 2,
            xmlid: "",
            name: "CRM",
            children: [],
            webIconData: "",
            webIcon: "bloop,bloop",
        },
    ]);
    // Initial Stored Values
    // There is no menu "CRM" in the initial values
    // menu_storage scopes the cache token to `${registry_hash}:${user.userId}`
    // so a shared browser cannot serve one user the menus of another
    // (the tree is filtered by access rights server-side). serverState's
    // default userId is 7; a bare hash is a miss, and a miss makes the boot
    // await `load_menus` — which this test deliberately never resolves before
    // asserting on the cached render.
    browser.localStorage.webclient_menus_version =
        "05500d71e084497829aa807e3caa2e7e9782ff702c15b2f57f87f2d64d049bd0:7";
    browser.localStorage.webclient_menus = JSON.stringify({
        1: {
            id: 1,
            appID: 1,
            actionID: 1,
            xmlid: "",
            name: "Partners",
            children: [],
            webIconData: "",
            webIcon: "bloop,bloop",
        },
        root: { id: "root", name: "root", appID: "root", children: [1] },
    });
    const webClient = await mountWebClient({ WebClient: WebClient });
    webClient.env.bus.addEventListener(AppEvent.MENUS_APP_CHANGED, () =>
        expect.step("Update Menus"),
    );
    expect(".o_home_menu").toHaveCount(1);
    expect(".o_app").toHaveCount(1);
    expect.verifySteps([]);
    def.resolve();
    await animationFrame();
    expect(".o_app").toHaveCount(2);
    expect(JSON.parse(browser.localStorage.webclient_menus)).toEqual({
        1: {
            actionID: 1,
            appID: 1,
            children: [],
            id: 1,
            name: "Partners",
            webIcon: "bloop,bloop",
            webIconData: "",
            xmlid: "",
        },
        2: {
            actionID: 2,
            appID: 2,
            children: [],
            id: 2,
            name: "CRM",
            webIcon: "bloop,bloop",
            webIconData: "",
            xmlid: "",
        },
        root: {
            appID: "root",
            children: [1, 2],
            id: "root",
            name: "root",
        },
    });
    expect.verifySteps(["Update Menus"]);
});
