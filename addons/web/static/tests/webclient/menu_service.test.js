// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { Deferred } from "@odoo/hoot-mock";
import {
    defineActions,
    defineMenus,
    defineModels,
    fields,
    getService,
    makeMockEnv,
    models,
    mountWebClient,
    onRpc,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { redirect } from "@web/core/utils/urls";

defineActions([
    {
        id: 666,
        xml_id: "action_1",
        name: "Partners Action 1",
        res_model: "partner",
        views: [[false, "kanban"]],
    },
]);

class Partner extends models.Model {
    name = fields.Char();
    foo = fields.Char();

    _records = [
        { id: 1, name: "First record", foo: "yop" },
        { id: 2, name: "Second record", foo: "blip" },
        { id: 3, name: "Third record", foo: "gnap" },
        { id: 4, name: "Fourth record", foo: "plop" },
        { id: 5, name: "Fifth record", foo: "zoup" },
    ];
    _views = {
        kanban: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="foo"/>
                    </t>
                </templates>
            </kanban>
        `,
        list: `<list><field name="foo"/></list>`,
        form: `
            <form>
                <group>
                    <field name="display_name"/>
                    <field name="foo"/>
                </group>
            </form>
        `,
        search: `<search><field name="foo" string="Foo"/></search>`,
    };
}
const { ResCompany, ResPartner, ResUsers } = webModels;
defineModels([Partner, ResCompany, ResPartner, ResUsers]);
defineMenus([
    {
        id: 1,
        children: [
            { id: 2, name: "Test1", appID: 1, actionID: 666 },
            { id: 3, name: "Test2", appID: 1, actionID: 666 },
        ],
        name: "App1",
        appID: 1,
        actionID: 666,
    },
]);

test.tags("desktop");
test(`use stored menus, and don't update on load_menus return (if identical)`, async () => {
    const def = new Deferred();
    redirect("/odoo/action-666");
    onRpc("/web/webclient/load_menus", () => def);

    // Initial Stored values
    browser.localStorage.webclient_menus_version =
        "05500d71e084497829aa807e3caa2e7e9782ff702c15b2f57f87f2d64d049bd0";
    browser.localStorage.webclient_menus = JSON.stringify({
        1: { appID: 1, children: [2, 3], name: "App1", id: 1, actionID: 666 },
        2: { appID: 1, children: [], name: "Test1", id: 2, actionID: 666 },
        3: { appID: 1, children: [], name: "Test2", id: 3, actionID: 666 },
        root: { id: "root", name: "root", appID: "root", children: [1] },
    });

    const webClient = await mountWebClient();
    webClient.env.bus.addEventListener("MENUS:APP-CHANGED", () =>
        expect.step("Don't Update"),
    );
    expect(`.o_menu_brand`).toHaveText("App1");
    expect(browser.sessionStorage.getItem("menu_id")).toBe("1");
    expect(".o_menu_sections").toHaveText("Test1\nTest2");
    def.resolve();
    await animationFrame();
    expect(".o_menu_sections").toHaveText("Test1\nTest2");
    expect.verifySteps([]);
});

test.tags("desktop");
test(`send stored hash and keep stored menus on 304 not modified`, async () => {
    const def = new Deferred();
    redirect("/odoo/action-666");
    onRpc("/web/webclient/load_menus", async (request) => {
        expect.step(`hash=${new URL(request.url).searchParams.get("hash")}`);
        await def;
        // Server-side payload hash matches: 304-equivalent, empty body.
        return new Response(null, { status: 304 });
    });

    // Initial stored values, including the persisted X-Menus-Hash value
    browser.localStorage.webclient_menus_version =
        "05500d71e084497829aa807e3caa2e7e9782ff702c15b2f57f87f2d64d049bd0";
    browser.localStorage.webclient_menus_hash = "abcdef123456";
    browser.localStorage.webclient_menus = JSON.stringify({
        1: { appID: 1, children: [2, 3], name: "App1", id: 1, actionID: 666 },
        2: { appID: 1, children: [], name: "Test1", id: 2, actionID: 666 },
        3: { appID: 1, children: [], name: "Test2", id: 3, actionID: 666 },
        root: { id: "root", name: "root", appID: "root", children: [1] },
    });

    const webClient = await mountWebClient();
    webClient.env.bus.addEventListener("MENUS:APP-CHANGED", () =>
        expect.step("Don't Update"),
    );
    expect(`.o_menu_brand`).toHaveText("App1");
    expect(".o_menu_sections").toHaveText("Test1\nTest2");
    expect.verifySteps(["hash=abcdef123456"]);
    def.resolve();
    await animationFrame();
    expect(".o_menu_sections").toHaveText("Test1\nTest2");
    expect(browser.localStorage.webclient_menus_hash).toBe("abcdef123456");
    expect.verifySteps([]);
});

test.tags("desktop");
test(`update menus and persist new hash on changed payload`, async () => {
    const def = new Deferred();
    redirect("/odoo/action-666");
    onRpc("/web/webclient/load_menus", async (request) => {
        expect.step(`hash=${new URL(request.url).searchParams.get("hash")}`);
        await def;
        return new Response(
            JSON.stringify({
                1: { appID: 1, children: [2], name: "App1", id: 1, actionID: 666 },
                2: { appID: 1, children: [], name: "Test1", id: 2, actionID: 666 },
                root: { id: "root", name: "root", appID: "root", children: [1] },
            }),
            { headers: { "X-Menus-Hash": "newhash789" } },
        );
    });

    // Stored copy contains an extra menu (Test2): the server payload differs
    browser.localStorage.webclient_menus_version =
        "05500d71e084497829aa807e3caa2e7e9782ff702c15b2f57f87f2d64d049bd0";
    browser.localStorage.webclient_menus_hash = "oldhash123";
    browser.localStorage.webclient_menus = JSON.stringify({
        1: { appID: 1, children: [2, 3], name: "App1", id: 1, actionID: 666 },
        2: { appID: 1, children: [], name: "Test1", id: 2, actionID: 666 },
        3: { appID: 1, children: [], name: "Test2", id: 3, actionID: 666 },
        root: { id: "root", name: "root", appID: "root", children: [1] },
    });

    const webClient = await mountWebClient();
    webClient.env.bus.addEventListener("MENUS:APP-CHANGED", () =>
        expect.step("Update Menus"),
    );
    // Stored copy is rendered without waiting for the revalidation
    expect(".o_menu_sections").toHaveText("Test1\nTest2");
    expect.verifySteps(["hash=oldhash123"]);
    def.resolve();
    await animationFrame();
    expect(".o_menu_sections").toHaveText("Test1");
    expect(browser.localStorage.webclient_menus_hash).toBe("newhash789");
    expect.verifySteps(["Update Menus"]);
});

test.tags("desktop");
test(`use stored menus, and update on load_menus return`, async () => {
    const def = new Deferred();
    redirect("/odoo/action-666");
    onRpc("/web/webclient/load_menus", () => def);

    // Initial Stored values
    // There is no menu "Test2" in the initial values
    browser.localStorage.webclient_menus_version =
        "05500d71e084497829aa807e3caa2e7e9782ff702c15b2f57f87f2d64d049bd0";
    browser.localStorage.webclient_menus = JSON.stringify({
        1: { id: 1, children: [2], name: "App1", appID: 1, actionID: 666 },
        2: { id: 2, children: [], name: "Test1", appID: 1, actionID: 666 },
        root: { id: "root", children: [1], name: "root", appID: "root" },
    });

    const webClient = await mountWebClient();
    webClient.env.bus.addEventListener("MENUS:APP-CHANGED", () =>
        expect.step("Update Menus"),
    );
    expect(`.o_menu_brand`).toHaveText("App1");
    expect(browser.sessionStorage.getItem("menu_id")).toBe("1");
    expect(".o_menu_sections").toHaveText("Test1");
    expect.verifySteps([]);
    def.resolve();
    await animationFrame();
    expect(".o_menu_sections").toHaveText("Test1\nTest2");
    expect(JSON.parse(browser.localStorage.webclient_menus)).toEqual({
        1: {
            actionID: 666,
            appID: 1,
            children: [2, 3],
            id: 1,
            name: "App1",
        },
        2: {
            actionID: 666,
            appID: 1,
            children: [],
            id: 2,
            name: "Test1",
        },
        3: {
            actionID: 666,
            appID: 1,
            children: [],
            id: 3,
            name: "Test2",
        },
        root: {
            appID: "root",
            children: [1],
            id: "root",
            name: "root",
        },
    });
    expect.verifySteps(["Update Menus"]);
});

test.tags("desktop");
test(`stale background revalidation cannot overwrite a fresher reload()`, async () => {
    const def = new Deferred();
    redirect("/odoo/action-666");
    onRpc("/web/webclient/load_menus", async (request) => {
        if (new URL(request.url).searchParams.get("hash")) {
            // Boot-time background revalidation: resolves late, with a
            // payload/hash that predate the reload() below.
            await def;
            return new Response(
                JSON.stringify({
                    1: {
                        appID: 1,
                        children: [],
                        name: "StaleApp",
                        id: 1,
                        actionID: 666,
                    },
                    root: { id: "root", name: "root", appID: "root", children: [1] },
                }),
                { headers: { "X-Menus-Hash": "stalehash" } },
            );
        }
        // reload(): full fetch, no conditional hash.
        return new Response(
            JSON.stringify({
                1: { appID: 1, children: [], name: "FreshApp", id: 1, actionID: 666 },
                root: { id: "root", name: "root", appID: "root", children: [1] },
            }),
            { headers: { "X-Menus-Hash": "freshhash" } },
        );
    });

    browser.localStorage.webclient_menus_version =
        "05500d71e084497829aa807e3caa2e7e9782ff702c15b2f57f87f2d64d049bd0";
    browser.localStorage.webclient_menus_hash = "boothash";
    browser.localStorage.webclient_menus = JSON.stringify({
        1: { appID: 1, children: [], name: "StoredApp", id: 1, actionID: 666 },
        root: { id: "root", name: "root", appID: "root", children: [1] },
    });

    await mountWebClient();
    await getService("menu").reload();
    expect(getService("menu").getMenu(1).name).toBe("FreshApp");

    // The stale revalidation resolves after the reload committed: it must
    // neither overwrite the menus nor persist its stale hash (which would
    // 304-pin the stale payload on the next boots).
    def.resolve();
    await animationFrame();
    expect(getService("menu").getMenu(1).name).toBe("FreshApp");
    expect(browser.localStorage.webclient_menus_hash).toBe("freshhash");
    expect(JSON.parse(browser.localStorage.webclient_menus)[1].name).toBe("FreshApp");
});

test.tags("desktop");
test(`total menu fetch failure falls back to an empty root`, async () => {
    // Cold boot (no stored copy), preload and refetch both fail: the menu
    // service must still expose a usable (empty) tree instead of leaving
    // menusData undefined and throwing on the first getAll()/getApps().
    const preload = Promise.reject(new Error("preload failed"));
    preload.catch(() => {}); // pre-handled: the service awaits it later
    patchWithCleanup(odoo, { loadMenusPromise: preload });
    onRpc("/web/webclient/load_menus", () => {
        throw new Error("load_menus unavailable");
    });
    await makeMockEnv();
    expect(getService("menu").getApps()).toEqual([]);
    expect(getService("menu").getAll().length).toBe(1);
    expect(getService("menu").getMenu("root").children).toEqual([]);
});

test.tags("desktop");
test(`cold boot: a null parse-time preload refetches menus (no blank client)`, async () => {
    // No stored menus for this registry version → cold path. The bootstrap
    // preload resolves null (a 304 the server computed against a stale
    // localStorage copy), which must NOT leave menusData undefined. The
    // service should refetch the full payload from the server instead.
    patchWithCleanup(odoo, { loadMenusPromise: Promise.resolve(null) });
    await makeMockEnv();
    // getApps() dereferences menusData.root — it throws if the cold boot left
    // it undefined (the blank-webclient bug).
    expect(
        getService("menu")
            .getApps()
            .map((app) => app.name),
    ).toEqual(["App1"]);
});

test.tags("desktop");
test(`cold boot: falls back to stored menus when preload is null and refetch fails`, async () => {
    // Version-mismatched stored copy present (still the cold path), the preload
    // resolves null, AND the server refetch rejects. Rather than a blank
    // client, the stale stored copy is served.
    browser.localStorage.webclient_menus_version = "stale-version-hash";
    browser.localStorage.webclient_menus = JSON.stringify({
        1: { appID: 1, children: [], name: "StoredApp", id: 1, actionID: 666 },
        root: { id: "root", name: "root", appID: "root", children: [1] },
    });
    patchWithCleanup(odoo, { loadMenusPromise: Promise.resolve(null) });
    onRpc("/web/webclient/load_menus", () => {
        throw new Error("load_menus unavailable");
    });
    await makeMockEnv();
    expect(
        getService("menu")
            .getApps()
            .map((app) => app.name),
    ).toEqual(["StoredApp"]);
});
