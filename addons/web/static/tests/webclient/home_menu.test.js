import {
    advanceTime,
    after,
    animationFrame,
    click,
    describe,
    drag,
    edit,
    expect,
    mockDate,
    mockTouch,
    pointerDown,
    press,
    queryAllAttributes,
    queryAllTexts,
    queryOne,
    runAllTimers,
    test,
} from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { Component, onRendered, reactive, useState, xml } from "@odoo/owl";
import {
    defineMenus,
    getService,
    makeMockEnv,
    mockService,
    mountWebClient,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { session } from "@web/session";
import "@web/webclient/home_menu/server_badges";
import { loadHomeMenuBadges } from "@web/webclient/home_menu/badges";
import { HomeMenu } from "@web/webclient/home_menu/home_menu";
import { QuickLauncher } from "@web/webclient/home_menu/quick_launcher";
import { computeHomeMenuProps } from "@web/webclient/home_menu/home_menu_service";
import { menuUsage } from "@web/webclient/menus/menu_usage";
import { parseHomeMenuConfig, reorderApps } from "@web/webclient/menus/menu_utils";
import { WebClient } from "@web/webclient/webclient";

/**
 * @param {Iterable<{
 *  index?: number;
 *  key: import("@odoo/hoot").KeyStrokes;
 *  shiftKey?: boolean;
 * }>} steps
 */
async function walkOn(steps) {
    for (const step of steps) {
        await press(step.key);
        await animationFrame();
        expect(`.o_menuitem:eq(${step.index || 0})`).toHaveClass("o_focused", {
            message: `step ${JSON.stringify(step)}`,
        });
    }
}

const getDefaultHomeMenuProps = () => {
    const apps = [
        {
            actionID: 121,
            href: "/odoo/action-121",
            appID: 1,
            id: 1,
            label: "Discuss",
            parents: "",
            webIcon: false,
            xmlid: "app.1",
        },
        {
            actionID: 122,
            href: "/odoo/action-122",
            appID: 2,
            id: 2,
            label: "Calendar",
            parents: "",
            webIcon: false,
            xmlid: "app.2",
        },
        {
            actionID: 123,
            href: "/odoo/contacts",
            appID: 3,
            id: 3,
            label: "Contacts",
            parents: "",
            webIcon: false,
            xmlid: "app.3",
        },
    ];
    return {
        apps,
        reorderApps: (/** @type {string[]} */ order) => reorderApps(apps, order),
    };
};

describe.current.tags("desktop");

test("ESC Support", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    mockService("home_menu", {
        async toggle(show) {
            expect.step(`toggle ${show}`);
        },
    });
    await press("escape");
    expect.verifySteps(["toggle false"]);
});

test("Click on an app", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    mockService("menu", {
        async selectMenu(menu) {
            // The service takes a menu or a bare id; the tests always pass the
            // menu, and saying so keeps the step readable either way.
            expect.step(
                `selectMenu ${typeof menu === "number" ? menu : /** @type {any} */ (menu).id}`,
            );
        },
    });
    await click(".o_menuitem:eq(0)");
    await animationFrame();
    expect.verifySteps(["selectMenu 1"]);
});

test("Display Expiration Panel (no module installed)", async () => {
    mockDate("2019-10-09T00:00:00");

    patchWithCleanup(session, {
        expiration_date: "2019-11-01 12:00:00",
        expiration_reason: "",
        isMailInstalled: false,
        warning: "admin",
    });

    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });

    expect(".database_expiration_panel").toHaveCount(1);
    expect(".database_expiration_panel .oe_instance_register").toHaveText(
        "You will be able to register your database once you have installed your first app.",
        { message: "There should be an expiration panel displayed" },
    );

    // Close the expiration panel
    await click(".database_expiration_panel .oe_instance_hide_panel");
    await animationFrame();
    expect(".database_expiration_panel").toHaveCount(0);
});

test("Navigation (only apps, only one line)", async () => {
    expect.assertions(8);

    const homeMenuProps = {
        apps: Array.from({ length: 3 }, (_, i) => ({
            actionID: 120 + i,
            href: "/odoo/act" + (120 + i),
            appID: i + 1,
            id: i + 1,
            label: `0${i}`,
            parents: "",
            webIcon: false,
            xmlid: `app.${i}`,
        })),
        reorderApps: (/** @type {string[]} */ order) =>
            reorderApps(homeMenuProps.apps, order),
    };
    await mountWithCleanup(HomeMenu, {
        props: homeMenuProps,
    });

    await walkOn([
        { key: "ArrowDown", index: 0 },
        { key: "ArrowRight", index: 1 },
        { key: "ArrowRight", index: 2 },
        { key: "ArrowRight", index: 0 },
        { key: "ArrowLeft", index: 2 },
        { key: "ArrowLeft", index: 1 },
        { key: "ArrowDown", index: 1 },
        { key: "ArrowUp", index: 1 },
    ]);
});

test("Navigation (only apps, two lines, one incomplete)", async () => {
    expect.assertions(19);

    const homeMenuProps = {
        apps: Array.from({ length: 8 }, (_, i) => ({
            actionID: 121,
            href: "/odoo/action-121",
            appID: i + 1,
            id: i + 1,
            label: `0${i}`,
            parents: "",
            webIcon: false,
            xmlid: `app.${i}`,
        })),
        reorderApps: (/** @type {string[]} */ order) =>
            reorderApps(homeMenuProps.apps, order),
    };
    await mountWithCleanup(HomeMenu, {
        props: homeMenuProps,
    });

    await walkOn([
        { key: "ArrowRight", index: 0 },
        { key: "ArrowUp", index: 6 },
        { key: "ArrowUp", index: 0 },
        { key: "ArrowDown", index: 6 },
        { key: "ArrowDown", index: 0 },
        { key: "ArrowRight", index: 1 },
        { key: "ArrowRight", index: 2 },
        { key: "ArrowUp", index: 7 },
        { key: "ArrowUp", index: 1 },
        { key: "ArrowRight", index: 2 },
        { key: "ArrowDown", index: 7 },
        { key: "ArrowDown", index: 1 },
        { key: "ArrowUp", index: 7 },
        { key: "ArrowRight", index: 6 },
        { key: "ArrowLeft", index: 7 },
        { key: "ArrowUp", index: 1 },
        { key: "ArrowLeft", index: 0 },
        { key: "ArrowLeft", index: 5 },
        { key: "ArrowRight", index: 0 },
    ]);
});

test("Navigation and open an app in the home menu", async () => {
    expect.assertions(6);

    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    mockService("menu", {
        async selectMenu(menu) {
            // The service takes a menu or a bare id; the tests always pass the
            // menu, and saying so keeps the step readable either way.
            expect.step(
                `selectMenu ${typeof menu === "number" ? menu : /** @type {any} */ (menu).id}`,
            );
        },
    });
    // No app selected so nothing to open
    await press("enter");
    expect.verifySteps([]);

    await walkOn([
        { key: "ArrowDown", index: 0 },
        { key: "ArrowRight", index: 1 },
        { key: "ArrowRight", index: 2 },
        { key: "ArrowLeft", index: 1 },
    ]);

    // open first app (Calendar)
    await press("enter");

    expect.verifySteps(["selectMenu 2"]);
});

test("Reorder apps in home menu using drag and drop", async () => {
    /** @type {import("@web/../tests/_framework/mock_server/mock_server").MenuDefinition[]} */
    const apps = [];
    for (let i = 0; i < 8; i++) {
        apps.push({
            actionID: 121,
            appID: i + 1,
            id: i + 1,
            name: `0${i}`,
            webIcon: false,
            xmlid: `app.${i}`,
        });
    }
    defineMenus(apps);

    onRpc("set_res_users_settings", () => {
        expect.step(`set_res_users_settings`);
        return {
            id: 1,
            homemenu_config:
                '["app.1","app.2","app.3","app.0","app.4","app.5","app.6","app.7"]',
        };
    });
    await mountWebClient({ WebClient: WebClient });
    await click(".o_home_menu_customize");
    await animationFrame();
    const { moveTo, drop } = await drag(".o_draggable:first-child");
    await moveTo(".o_draggable:first-child", {
        position: {
            x: 70,
            y: 35,
        },
        relative: true,
    });
    await drop(".o_draggable:not(.o_dragged):eq(3)");
    await animationFrame();
    expect.verifySteps(["set_res_users_settings"]);
    expect(".o_app:eq(0)").toHaveAttribute("data-menu-xmlid", "app.1", {
        message: "first displayed app has app.1 xmlid",
    });
    expect(".o_app:eq(3)").toHaveAttribute("data-menu-xmlid", "app.0", {
        message: "app 0 is now at 4th position",
    });
});

test("The HomeMenu input takes the focus when you press a key only if no other element is the activeElement", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    expect(".o_home_menu_search").toBeFocused();

    const activeElement = document.createElement("div");
    getService("ui").activateElement(activeElement);
    // remove the focus from the input
    const otherInput = document.createElement("input");
    queryOne(".o_home_menu").appendChild(otherInput);
    await pointerDown(otherInput);
    await pointerDown(document.body);
    expect(document.body).toBeFocused();
    expect(".o_home_menu_search").not.toBeFocused();

    await press("a");
    await animationFrame();
    expect(document.body).toBeFocused();
    expect(".o_home_menu_search").not.toBeFocused();

    getService("ui").deactivateElement(activeElement);
    await press("a");
    await animationFrame();
    expect(".o_home_menu_search").toBeFocused();
    expect(".o_home_menu_search").toHaveValue("a");
});

test("the search input takes the focus back after a blur onto the body", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    expect(".o_home_menu_search").toBeFocused();

    await pointerDown(document.body);
    expect(document.body).toBeFocused();
    await runAllTimers();
    expect(".o_home_menu_search").toBeFocused();

    const activeElement = document.createElement("div");
    getService("ui").activateElement(activeElement);
    await pointerDown(document.body);
    expect(document.body).toBeFocused();
    await runAllTimers();
    expect(document.body).toBeFocused({
        message: "another active element owns the focus, the home menu leaves it alone",
    });
    getService("ui").deactivateElement(activeElement);
});

test("The HomeMenu input does not take the focus if it is already on another input", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    expect(".o_home_menu_search").toBeFocused();

    const otherInput = document.createElement("input");
    queryOne(".o_home_menu").appendChild(otherInput);
    await pointerDown(otherInput);
    await press("a");
    await animationFrame();
    expect(otherInput).toBeFocused();
    expect(".o_home_menu_search").not.toBeFocused();

    otherInput.remove();
    await press("a");
    await animationFrame();
    expect(".o_home_menu_search").toBeFocused();
    expect(".o_home_menu_search").toHaveValue("a");
});

test("The HomeMenu input does not take the focus if it is already on a textarea", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    expect(".o_home_menu_search").toBeFocused();

    const textarea = document.createElement("textarea");
    queryOne(".o_home_menu").appendChild(textarea);
    await pointerDown(textarea);
    await press("a");
    await animationFrame();
    expect(textarea).toBeFocused();
    expect(".o_home_menu_search").not.toBeFocused();

    textarea.remove();
    await press("a");
    await animationFrame();
    expect(".o_home_menu_search").toBeFocused();
    expect(".o_home_menu_search").toHaveValue("a");
});

test("home search input shouldn't be focused on touch devices", async () => {
    mockTouch(true);
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    expect(".o_home_menu_search").not.toBeFocused({
        message: "home menu search input shouldn't have the focus",
    });
});

test("home keynav not triggering when navigating a dropdown", async () => {
    /** @type {import("@web/../tests/_framework/mock_server/mock_server").MenuDefinition[]} */
    const apps = [];
    for (let i = 0; i < 8; i++) {
        apps.push({
            actionID: 121,
            appID: i + 1,
            id: i + 1,
            name: `0${i}`,
            webIcon: false,
            xmlid: `app.${i}`,
        });
    }
    defineMenus(apps);

    await mountWebClient({ WebClient: WebClient });

    await click(".o_user_menu .o-dropdown");
    await animationFrame();

    await press("arrowdown");
    await animationFrame();
    expect(".o-dropdown-item.focus").toHaveCount(1);

    await press("arrowleft");
    await animationFrame();
    expect(".o-dropdown-item.focus").toHaveCount(1);
    expect(".o_app.o_focused").toHaveCount(0);
});

test("no recents row until an app has been opened", async () => {
    menuUsage.clear();
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    expect(".o_recent_apps").toHaveCount(0);
    expect(".o_apps_listbox").toHaveClass("mt-5");
});

test("recently opened apps are shown above the grid", async () => {
    menuUsage.clear();
    menuUsage.record({ xmlid: "app.2" });
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    expect(".o_recent_apps .o_app").toHaveCount(1);
    expect(".o_recent_apps .o_caption").toHaveText("Calendar");
    expect(".o_recent_apps .o_app").not.toHaveAttribute("data-menu-xmlid", undefined, {
        message: "a recent tile is not a drag or tour target: the grid tile is",
    });
    expect(".o_apps .o_app").toHaveCount(3);
    menuUsage.clear();
});

test("alt+n opens the nth app", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    mockService("menu", {
        async selectMenu(menu) {
            expect.step(`selectMenu ${/** @type {any} */ (menu).id}`);
        },
    });
    expect(".o_apps .o_app:eq(1)").toHaveAttribute("data-hotkey", "2");
    await press(["alt", "2"]);
    await runAllTimers();
    expect.verifySteps(["selectMenu 2"]);
});

test("Tab reaches the tiles and the arrows then move the real focus", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    expect(".o_home_menu_search").toBeFocused();

    await press("Tab");
    expect(".o_home_menu_customize").toBeFocused();
    await press("Tab");
    await animationFrame();
    expect(".o_app:eq(0)").toBeFocused();
    expect(".o_app:eq(0)").toHaveClass("o_focused");

    await press("ArrowRight");
    await animationFrame();
    expect(".o_app:eq(1)").toBeFocused();
    expect(".o_app:eq(1)").toHaveClass("o_focused");
    expect(".o_home_menu_search").not.toBeFocused();
});

test("a namespace character typed in the search reaches the palette as such", async () => {
    await mountWithCleanup(HomeMenu, {
        props: getDefaultHomeMenuProps(),
    });
    mockService("command", {
        openMainPalette(config) {
            expect.step(config.searchValue);
        },
    });
    patchWithCleanup(registry.category("command_setup"), {
        contains: (key) => key === "@" || key === "/",
    });
    const input = /** @type {HTMLInputElement} */ (queryOne(".o_home_menu_search"));
    for (const typed of ["cal", "@bob"]) {
        input.value = typed;
        input.dispatchEvent(new InputEvent("input", { bubbles: true }));
    }
    expect(".o_home_menu_search").toHaveValue("", {
        message: "the box hands its text to the palette and empties",
    });
    expect.verifySteps(["@bob"], { message: "a plain query never opens the palette" });
});

/** @param {unknown} [raw] */
function getLayoutProps(raw) {
    const props = getDefaultHomeMenuProps();
    const config = reactive(parseHomeMenuConfig(raw));
    const defaultOrder = props.apps.map((app) => app.xmlid);
    return {
        ...props,
        config,
        resetApps: () => reorderApps(props.apps, defaultOrder),
    };
}

test("pinning an app moves it first and persists the versioned layout", async () => {
    onRpc("set_res_users_settings", ({ kwargs }) => {
        expect.step(kwargs.new_settings.homemenu_config);
        return {};
    });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    expect(".o_app_edit_actions").toHaveCount(0);
    expect(".o_pinned_apps").toHaveCount(0);

    await click(".o_home_menu_customize");
    await animationFrame();
    expect(".o_app_edit_actions").toHaveCount(3);

    await click(".o_app[data-menu-xmlid='app.3'] .o_app_pin");
    await animationFrame();
    expect(".o_pinned_apps .o_app").toHaveCount(1);
    expect(".o_app:eq(0)").toHaveAttribute("data-menu-xmlid", "app.3");
    expect(".o_app:eq(0)").toHaveClass("o_app_pinned");
    expect(".o_app:eq(0)").toHaveAttribute("id", "result_app_0");
    expect(".o_app:eq(1)").toHaveAttribute("id", "result_app_1");
    expect.verifySteps(['{"version":2,"order":[],"pinned":["app.3"],"hidden":[]}']);

    await click(".o_app[data-menu-xmlid='app.3'] .o_app_pin");
    await animationFrame();
    expect(".o_pinned_apps").toHaveCount(0);
    expect(".o_app:eq(0)").toHaveAttribute("data-menu-xmlid", "app.1");
    expect.verifySteps(['{"version":2,"order":[],"pinned":[],"hidden":[]}']);
});

test("hiding an app removes it from the grid and shows it dimmed while editing", async () => {
    onRpc("set_res_users_settings", () => ({}));
    await mountWithCleanup(HomeMenu, { props: getLayoutProps('{"pinned":["app.2"]}') });
    expect(".o_app").toHaveCount(3);
    expect(".o_app:eq(0)").toHaveAttribute("data-menu-xmlid", "app.2");

    await click(".o_home_menu_customize");
    await animationFrame();
    await click(".o_app[data-menu-xmlid='app.2'] .o_app_hide");
    await animationFrame();
    expect(".o_app[data-menu-xmlid='app.2']").toHaveClass("o_app_hidden");
    expect(".o_app[data-menu-xmlid='app.2']").not.toHaveClass("o_app_pinned", {
        message: "a hidden app is unpinned",
    });
    expect(".o_app").toHaveCount(3);

    await click(".o_home_menu_done");
    await animationFrame();
    expect(".o_app").toHaveCount(2);
    expect(".o_app[data-menu-xmlid='app.2']").toHaveCount(0);
});

test("reset layout clears the order, the pins and the hidden apps", async () => {
    onRpc("set_res_users_settings", ({ kwargs }) => {
        expect.step(String(kwargs.new_settings.homemenu_config));
        return {};
    });
    const props = getLayoutProps(
        '{"order":["app.3","app.1","app.2"],"pinned":["app.2"],"hidden":["app.1"]}',
    );
    reorderApps(props.apps, props.config.order);
    await mountWithCleanup(HomeMenu, { props });
    expect(queryAllTexts(".o_app .o_caption")).toEqual(["Calendar", "Contacts"]);

    await click(".o_home_menu_customize");
    await animationFrame();
    expect(".o_home_menu_reset").toHaveCount(1);
    await click(".o_home_menu_reset");
    await animationFrame();
    expect(queryAllTexts(".o_app .o_caption")).toEqual([
        "Discuss",
        "Calendar",
        "Contacts",
    ]);
    expect(".o_home_menu_reset").toHaveCount(0);
    expect.verifySteps(["null"]);
});

test("Escape leaves the edit mode before it closes the home menu", async () => {
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    mockService("home_menu", {
        async toggle(show) {
            expect.step(`toggle ${show}`);
        },
    });
    await click(".o_home_menu_customize");
    await animationFrame();
    await press("escape");
    await animationFrame();
    expect(".o_home_menu_done").toHaveCount(0);
    expect.verifySteps([]);
    await press("escape");
    expect.verifySteps(["toggle false"]);
});

test("the company default applies until the user customises, and reset returns to it", async () => {
    onRpc("set_res_users_settings", ({ kwargs }) => {
        expect.step(`settings ${kwargs.new_settings.homemenu_config}`);
        return {};
    });
    const props = getLayoutProps('{"pinned":["app.2"]}');
    props.defaultConfig = parseHomeMenuConfig('{"pinned":["app.2"]}');
    await mountWithCleanup(HomeMenu, { props });
    expect(".o_app:eq(0)").toHaveAttribute("data-menu-xmlid", "app.2");

    await click(".o_home_menu_customize");
    await animationFrame();
    expect(".o_home_menu_reset").toHaveCount(0, {
        message: "the company layout, untouched, is nothing to reset",
    });

    await click(".o_app[data-menu-xmlid='app.3'] .o_app_pin");
    await animationFrame();
    expect(".o_home_menu_reset").toHaveCount(1);
    expect(queryAllTexts(".o_pinned_apps .o_caption")).toEqual([
        "Calendar",
        "Contacts",
    ]);
    expect.verifySteps([
        'settings {"version":2,"order":[],"pinned":["app.2","app.3"],"hidden":[]}',
    ]);

    await click(".o_home_menu_reset");
    await animationFrame();
    expect(queryAllTexts(".o_pinned_apps .o_caption")).toEqual(["Calendar"]);
    expect(".o_home_menu_reset").toHaveCount(0);
    expect.verifySteps(["settings null"]);
});

test("an admin can make the current layout the company default", async () => {
    patchWithCleanup(user, { isAdmin: true });
    onRpc("set_res_users_settings", () => ({}));
    onRpc("res.company", "write", ({ args }) => {
        expect.step(
            `company ${args[0]} ${JSON.stringify(args[1].homemenu_default_config)}`,
        );
        return true;
    });
    const props = getLayoutProps();
    props.defaultConfig = parseHomeMenuConfig(null);
    await mountWithCleanup(HomeMenu, { props });

    await click(".o_home_menu_customize");
    await animationFrame();
    expect(".o_home_menu_company_default").toHaveCount(0);

    await click(".o_app[data-menu-xmlid='app.3'] .o_app_hide");
    await animationFrame();
    await click(".o_home_menu_company_default");
    await animationFrame();
    expect.verifySteps([
        `company ${user.activeCompany.id} {"version":2,"order":[],"pinned":[],"hidden":["app.3"]}`,
    ]);
    expect(session.homemenu_default_config).toEqual({
        version: 2,
        order: [],
        pinned: [],
        hidden: ["app.3"],
    });
    expect(".o_home_menu_reset").toHaveCount(0, {
        message: "the layout is the company default now, so there is nothing to reset",
    });
    expect(".o_home_menu_company_default").toHaveCount(0);
});

test("setting the company default with no default passed in still clears the reset", async () => {
    // `defaultConfig` is an optional prop, and the fallback used to be minted
    // fresh per read: the layout was written to a copy nobody read, so the
    // launcher went on offering to reset a layout that was now the default.
    patchWithCleanup(user, { isAdmin: true });
    onRpc("set_res_users_settings", () => ({}));
    onRpc("res.company", "write", () => true);
    const props = getLayoutProps();
    delete props.defaultConfig;
    const homeMenu = await mountWithCleanup(HomeMenu, { props });

    await click(".o_home_menu_customize");
    await animationFrame();
    await click(".o_app[data-menu-xmlid='app.3'] .o_app_hide");
    await animationFrame();
    expect(".o_home_menu_reset").toHaveCount(1);
    expect(".o_home_menu_company_default").toHaveCount(1);

    await click(".o_home_menu_company_default");
    await animationFrame();
    expect(homeMenu.layout.defaultConfig.hidden).toEqual(["app.3"]);
    expect(".o_home_menu_reset").toHaveCount(0, {
        message: "this layout is the company's now, so there is nothing to reset",
    });
    expect(".o_home_menu_company_default").toHaveCount(0);
});

test("a user without a layout of their own gets the company default", async () => {
    patchWithCleanup(session, {
        homemenu_default_config: {
            version: 2,
            order: [],
            pinned: ["menu_2"],
            hidden: ["menu_1"],
        },
    });
    defineMenus([
        { id: 1, name: "App1", appID: 1, actionID: 1001, xmlid: "menu_1" },
        { id: 2, name: "App2", appID: 2, actionID: 1002, xmlid: "menu_2" },
        { id: 3, name: "App3", appID: 3, actionID: 1003, xmlid: "menu_3" },
    ]);
    await mountWebClient({ WebClient });
    expect(queryAllTexts(".o_apps_listbox .o_caption")).toEqual(["App2", "App3"]);
    expect(".o_pinned_apps .o_app").toHaveCount(1);
});

test("tiles show the counts the badge providers answer with, summed", async () => {
    const badgeRegistry = registry.category("home_menu_badges");
    badgeRegistry.add("first", { provide: () => ({ "app.2": 3 }) });
    badgeRegistry.add("second", {
        provide: async () => ({ "app.2": 2, "app.3": 120 }),
    });
    badgeRegistry.add("broken", { provide: () => Promise.reject(new Error("no")) });
    after(() => {
        badgeRegistry.remove("first");
        badgeRegistry.remove("second");
        badgeRegistry.remove("broken");
    });
    expect.errors(0);
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    await animationFrame();
    expect(".o_app[data-menu-xmlid='app.1'] .o_app_badge").toHaveCount(0);
    expect(".o_app[data-menu-xmlid='app.2'] .o_app_badge").toHaveText("5");
    expect(".o_app[data-menu-xmlid='app.2'] .o_app_badge").toHaveAttribute(
        "aria-label",
        "5 pending",
    );
    expect(".o_app[data-menu-xmlid='app.3'] .o_app_badge").toHaveText("99+");

    await click(".o_home_menu_customize");
    await animationFrame();
    expect(".o_app_badge").toHaveCount(0, {
        message: "the edit buttons take the corner",
    });
});

test("outside the edit mode a hold on a tile is not a drag", async () => {
    onRpc("set_res_users_settings", () => {
        expect.step("set_res_users_settings");
        return {};
    });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    const { moveTo, drop } = await drag(".o_draggable:first-child");
    await advanceTime(600);
    expect(".o_dragged_app").toHaveCount(0);
    await moveTo(".o_draggable:eq(2)");
    await drop(".o_draggable:eq(2)");
    await animationFrame();
    expect(".o_app:eq(0)").toHaveAttribute("data-menu-xmlid", "app.1");
    expect.verifySteps([]);
});

test("the arrows move the real focus from the search box onto the tiles, a letter brings it back", async () => {
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    expect(".o_home_menu_search").toBeFocused();
    expect(".o_home_menu_search").not.toHaveAttribute("aria-activedescendant");
    expect(".o_app[role]").toHaveCount(0, {
        message: "a tile is a link, nothing else",
    });

    await press("ArrowDown");
    await animationFrame();
    expect(".o_app:eq(0)").toBeFocused();
    await press("ArrowRight");
    await animationFrame();
    expect(".o_app:eq(1)").toBeFocused();
    expect(".o_app:eq(1)").toHaveClass("o_focused");

    await press("a");
    await animationFrame();
    expect(".o_home_menu_search").toBeFocused({
        message: "typing on a tile searches, as it does from the box",
    });
    expect(".o_home_menu_search").toHaveValue("a");
});

test("with a pinned row the arrows follow the rows on screen, not one flat grid", async () => {
    const props = getLayoutProps('{"pinned":["app.1"]}');
    props.apps = Array.from({ length: 8 }, (_, i) => ({
        actionID: 121,
        href: "/odoo/action-121",
        appID: i + 1,
        id: i + 1,
        label: `0${i}`,
        parents: "",
        webIcon: false,
        xmlid: `app.${i}`,
    }));
    await mountWithCleanup(HomeMenu, { props });
    expect(queryAllTexts(".o_pinned_apps .o_caption")).toEqual(["01"]);

    await walkOn([
        { key: "ArrowDown", index: 0 }, // the pinned tile
        { key: "ArrowDown", index: 1 }, // the tile below it: first of the next row
        { key: "ArrowRight", index: 2 },
        { key: "ArrowDown", index: 7 }, // last row has one tile, column clamps
        { key: "ArrowDown", index: 0 }, // wraps to the pinned row
        { key: "ArrowUp", index: 7 },
        { key: "ArrowUp", index: 1 }, // back on the six-wide row, same column
    ]);
});

const EMPTY_TREE = { id: "root", name: "root", appID: "root", childrenTree: [] };

function searchFor(text) {
    const input = /** @type {HTMLInputElement} */ (queryOne(".o_home_menu_search"));
    input.value = text;
    input.dispatchEvent(new InputEvent("input", { bubbles: true }));
    return animationFrame();
}

test("the search box filters the tiles in place and lists the matching menus", async () => {
    mockService("menu", {
        getMenuAsTree: () => ({
            id: "root",
            name: "root",
            appID: "root",
            childrenTree: [
                {
                    id: 1,
                    name: "Discuss",
                    appID: 1,
                    actionID: 121,
                    childrenTree: [
                        {
                            id: 11,
                            name: "Channels",
                            appID: 1,
                            actionID: 122,
                            childrenTree: [],
                        },
                    ],
                },
                {
                    id: 2,
                    name: "Calendar",
                    appID: 2,
                    actionID: 121,
                    childrenTree: [
                        {
                            id: 21,
                            name: "Calls",
                            appID: 2,
                            actionID: 123,
                            childrenTree: [],
                        },
                    ],
                },
            ],
        }),
        async selectMenu(menu) {
            expect.step(`selectMenu ${/** @type {any} */ (menu).id}`);
        },
    });
    menuUsage.record({ xmlid: "app.3" });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps('{"pinned":["app.1"]}') });
    expect(".o_pinned_apps").toHaveCount(1);
    expect(".o_recent_apps").toHaveCount(1);

    await searchFor("cal");
    expect(queryAllTexts(".o_apps_listbox .o_caption")).toEqual(["Calendar"]);
    expect(".o_pinned_apps").toHaveCount(0, { message: "a query is one flat list" });
    expect(".o_recent_apps").toHaveCount(0);
    expect(queryAllTexts(".o_home_menu_menu_results .o_menu_result")).toEqual(
        ["Calendar / Calls", "Discuss / Channels"],
        { message: "the fuzzy match ranks the closer name first" },
    );
    expect(".o_command_palette").toHaveCount(0, { message: "no second search box" });

    await click(".o_home_menu_menu_results .o_menu_result");
    expect.verifySteps(["selectMenu 21"]);

    await searchFor("zzz");
    expect(".o_apps_listbox").toHaveCount(0);
    expect(".o_no_result").toHaveText("No apps or menus match");

    await press("escape");
    await animationFrame();
    expect(".o_home_menu_search").toHaveValue("");
    expect(queryAllTexts(".o_apps_listbox .o_caption")).toEqual([
        "Discuss",
        "Calendar",
        "Contacts",
    ]);
    menuUsage.clear();
});

test("Enter in the search box opens the first matching app, or the first menu", async () => {
    mockService("menu", {
        getMenuAsTree: () => ({
            id: "root",
            name: "root",
            appID: "root",
            childrenTree: [
                {
                    id: 3,
                    name: "Contacts",
                    appID: 3,
                    actionID: 121,
                    childrenTree: [
                        {
                            id: 31,
                            name: "Vendors",
                            appID: 3,
                            actionID: 124,
                            childrenTree: [],
                        },
                    ],
                },
            ],
        }),
        async selectMenu(menu) {
            expect.step(`selectMenu ${/** @type {any} */ (menu).id}`);
        },
    });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    await searchFor("cont");
    await press("enter");
    expect.verifySteps(["selectMenu 3"]);

    await searchFor("vend");
    expect(".o_apps_listbox").toHaveCount(0);
    await press("enter");
    expect.verifySteps(["selectMenu 31"]);
});

test("with a query on, the arrows walk the tiles and then the matching menus", async () => {
    mockService("menu", {
        getMenuAsTree: () => ({
            id: "root",
            name: "root",
            appID: "root",
            childrenTree: [
                {
                    id: 2,
                    name: "Calendar",
                    appID: 2,
                    actionID: 121,
                    childrenTree: [
                        {
                            id: 21,
                            name: "Calls",
                            appID: 2,
                            actionID: 123,
                            childrenTree: [],
                        },
                        {
                            id: 22,
                            name: "Calc",
                            appID: 2,
                            actionID: 124,
                            childrenTree: [],
                        },
                    ],
                },
            ],
        }),
        async selectMenu(menu) {
            expect.step(`selectMenu ${/** @type {any} */ (menu).id}`);
        },
    });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    await searchFor("cal");
    expect(queryAllTexts(".o_apps_listbox .o_caption")).toEqual(["Calendar"]);
    expect(".o_menu_result").toHaveCount(2);

    await press("ArrowDown");
    await animationFrame();
    expect(".o_app:eq(0)").toBeFocused();
    await press("ArrowDown");
    await animationFrame();
    expect(".o_menu_result:eq(0)").toBeFocused();
    expect(".o_menu_result:eq(0)").toHaveClass("o_focused");
    await press("ArrowDown");
    await animationFrame();
    expect(".o_menu_result:eq(1)").toBeFocused();
    await press("ArrowDown");
    await animationFrame();
    expect(".o_app:eq(0)").toBeFocused({ message: "wraps back to the first tile" });
    await press("ArrowUp");
    await animationFrame();
    expect(".o_menu_result:eq(1)").toBeFocused();

    await press("enter");
    expect.verifySteps(["selectMenu 22"]);
});

/**
 * @param {string[]} xmlids
 * @param {number} [childrenPerApp] deeper menus, which is what the search box
 *  lists under the tiles
 */
function menuTreeOf(xmlids, childrenPerApp = 0) {
    let childId = 10000;
    return {
        id: "root",
        name: "root",
        appID: "root",
        childrenTree: xmlids.map((xmlid, i) => ({
            id: i + 1,
            appID: i + 1,
            name: xmlid.toUpperCase(),
            actionID: 100 + i,
            xmlid,
            webIcon: false,
            childrenTree: Array.from({ length: childrenPerApp }, (_, c) => ({
                id: childId++,
                appID: i + 1,
                name: `App submenu ${c}`,
                actionID: childId,
                xmlid: `${xmlid}.sub${c}`,
                childrenTree: [],
            })),
        })),
    };
}

test("reset after publishing a company default returns the TILES to it, not only the config", async () => {
    // resetApps used to close over the layout read at mount, so publishing a
    // new company default left it resetting to the old one: the config said
    // one order and the grid showed another.
    patchWithCleanup(user, { isAdmin: true, settings: {} });
    patchWithCleanup(session, { homemenu_default_config: null });
    onRpc("set_res_users_settings", () => ({}));
    onRpc("res.company", "write", () => true);
    const tree = menuTreeOf(["a", "b", "c"]);
    const menus = { getMenuAsTree: () => tree, selectMenu: () => {} };
    mockService("menu", menus);
    const props = computeHomeMenuProps(menus);
    const homeMenu = await mountWithCleanup(HomeMenu, { props });

    props.reorderApps(["c", "a", "b"]);
    homeMenu.layout.config.order = ["c", "a", "b"];
    await homeMenu._setCompanyDefault();
    await animationFrame();

    props.reorderApps(["b", "c", "a"]);
    homeMenu.layout.config.order = ["b", "c", "a"];
    await animationFrame();
    expect(queryAllAttributes(".o_apps .o_app", "data-menu-xmlid")).toEqual([
        "b",
        "c",
        "a",
    ]);

    await homeMenu._resetLayout();
    await animationFrame();
    expect(homeMenu.layout.config.order).toEqual(["c", "a", "b"]);
    expect(queryAllAttributes(".o_apps .o_app", "data-menu-xmlid")).toEqual(
        ["c", "a", "b"],
        { message: "the grid follows the company default the admin just set" },
    );
});

test("a keystroke evaluates each derived list once per render, not once per result row", async () => {
    // The matching-menu rows used to ask for the app grid's length one row at
    // a time, so eight rows rebuilt the pinned map and the fuzzy-matched list
    // eight times over, per render, per character typed.
    //
    // Counted on the computations, not on the reads: the getters are now memo
    // readers over one cache per render, and the whole point of that cache is
    // that reading a list twice is free. What must stay at one per render is
    // the walk over every app and every menu, which is `_<name>()`.
    const counts = { shownApps: 0, pinnedApps: 0, unpinnedApps: 0, menuMatches: 0 };
    let renders = 0;
    class Counted extends HomeMenu {
        setup() {
            super.setup();
            onRendered(() => renders++);
        }
    }
    for (const name of Object.keys(counts)) {
        const compute = HomeMenu.prototype[`_${name}`];
        Counted.prototype[`_${name}`] = function () {
            counts[name]++;
            return compute.call(this);
        };
    }
    const xmlids = Array.from({ length: 20 }, (_, i) => `app${i}`);
    const tree = menuTreeOf(xmlids, 5);
    mockService("menu", { getMenuAsTree: () => tree, selectMenu: () => {} });
    const apps = xmlids.map((xmlid, i) => ({
        actionID: 100 + i,
        href: `/odoo/action-${100 + i}`,
        appID: i + 1,
        id: i + 1,
        label: `App ${i}`,
        parents: "",
        webIcon: false,
        xmlid,
    }));
    await mountWithCleanup(Counted, {
        props: { apps, reorderApps: (o) => reorderApps(apps, o) },
    });
    await animationFrame();
    renders = 0;
    for (const k of Object.keys(counts)) {
        counts[k] = 0;
    }
    await click(".o_home_menu_search");
    await edit("app", { confirm: false });
    await animationFrame();

    expect(renders).toBe(3, { message: "one render per character" });
    expect(".o_menu_result").toHaveCount(8, { message: "eight rows on screen" });
    for (const [name, n] of Object.entries(counts)) {
        expect(n).toBeLessThanOrEqual(renders, {
            message: `${name}: at most once per render`,
        });
    }
    // `shownApps` is not one of them under a query: a query searches every app
    // the user has, hidden ones included, so the layout filter never runs.
    expect(counts.shownApps).toBe(0);
    expect(counts.unpinnedApps).toBe(renders);
    expect(counts.menuMatches).toBe(renders);
});

test("two quick pins are written one after the other, so neither can be lost", async () => {
    // res.users.settings writes are not serialised, so this used to put two
    // whole layouts in flight at once -- {pinned:[a]} and {pinned:[a,b]} --
    // and whichever reached the server last won. Losing the second pin left
    // nothing behind to show it had happened. Two clicks are two writes,
    // being a tick apart; what changed is that the second waits.
    patchWithCleanup(user, { settings: { id: 1 } });
    const pending = [];
    onRpc("set_res_users_settings", ({ kwargs }) => {
        const def = new Deferred();
        pending.push(def);
        expect.step(kwargs.new_settings.homemenu_config);
        return def;
    });
    const apps = ["a", "b"].map((xmlid, i) => ({
        actionID: 100 + i,
        href: `/odoo/action-${100 + i}`,
        appID: i + 1,
        id: i + 1,
        label: xmlid.toUpperCase(),
        parents: "",
        webIcon: false,
        xmlid,
    }));
    await mountWithCleanup(HomeMenu, {
        props: {
            apps,
            config: reactive(parseHomeMenuConfig(null)),
            reorderApps: (order) => reorderApps(apps, order),
        },
    });
    await click(".o_home_menu_customize");
    await animationFrame();

    await click(".o_app[data-menu-xmlid='a'] .o_app_pin");
    await click(".o_app[data-menu-xmlid='b'] .o_app_pin");
    await animationFrame();
    expect(pending).toHaveLength(1, {
        message: "one request in flight: the second waits for the first",
    });
    expect.verifySteps(['{"version":2,"order":[],"pinned":["a"],"hidden":[]}']);

    pending[0].resolve({});
    await animationFrame();
    expect(pending).toHaveLength(2);
    expect.verifySteps(['{"version":2,"order":[],"pinned":["a","b"],"hidden":[]}'], {
        message: "and the later layout goes out last, carrying both pins",
    });
});

test("a count too wide for an icon is shown as 99+, by the same rule in both launchers", async () => {
    const badgeRegistry = registry.category("home_menu_badges");
    badgeRegistry.add("ceiling", {
        provide: () => ({ "app.1": 99, "app.2": 100, "app.3": 4200 }),
    });
    await mountWithCleanup(HomeMenu, { props: getDefaultHomeMenuProps() });
    await animationFrame();
    // Scoped to the grid throughout: an app with a count also appears in the
    // Needs attention row above it, so an unscoped selector reads every badge
    // twice, and in that section's order rather than the grid's.
    expect(queryAllTexts(".o_apps_listbox .o_app_badge")).toEqual(
        ["99", "99+", "99+"],
        { message: "99 still fits; anything above it does not" },
    );
    expect(
        ".o_apps_listbox .o_app[data-menu-xmlid='app.2'] .o_app_badge",
    ).toHaveAttribute("aria-label", "100 pending", {
        message: "the reader is told the real number, not the shortened one",
    });
});

test("a menu reload that changes the apps re-counts their badges", async () => {
    let counted = [];
    registry.category("home_menu_badges").add("recount", {
        provide: (env, apps) => {
            counted = apps.map((app) => app.xmlid);
            return {};
        },
    });
    const base = getDefaultHomeMenuProps();
    const newApp = {
        actionID: 124,
        href: "/odoo/action-124",
        appID: 4,
        id: 4,
        label: "Helpdesk",
        parents: "",
        webIcon: false,
        xmlid: "app.4",
    };
    // A parent that can hand the launcher a different app list, which is what
    // HomeMenuAction does on MENUS_APP_CHANGED.
    class Parent extends Component {
        static components = { HomeMenu };
        static props = {};
        static template = xml`<HomeMenu t-props="state.props"/>`;
        setup() {
            this.state = useState({ props: base });
        }
    }
    const parent = await mountWithCleanup(Parent);
    await animationFrame();
    expect(counted).toEqual(["app.1", "app.2", "app.3"]);

    counted = [];
    parent.state.props = { ...base, apps: [...base.apps, newApp] };
    await animationFrame();
    expect(counted).toEqual(["app.1", "app.2", "app.3", "app.4"], {
        message: "the new app is counted, not left blank until the next visit",
    });

    // A re-render that changes no app must not re-count: MENUS_APP_CHANGED
    // also fires for a plain navigation, and a provider may cost a request.
    counted = [];
    parent.state.props = { ...base, apps: [...base.apps, newApp] };
    await animationFrame();
    expect(counted).toEqual([], { message: "same apps, no second count" });
});

test("a re-render that leaves the grid alone keeps the keyboard selection", async () => {
    // MENUS_APP_CHANGED fires for a plain navigation too, and HomeMenuAction
    // answers it by recomputing props -- a fresh array and a fresh layout
    // holding exactly the same apps. That used to drop the user's selection.
    const base = getDefaultHomeMenuProps();
    class Parent extends Component {
        static components = { HomeMenu };
        static props = {};
        static template = xml`<HomeMenu t-props="state.props"/>`;
        setup() {
            this.state = useState({ props: base });
        }
    }
    const parent = await mountWithCleanup(Parent);
    await press("ArrowDown");
    await animationFrame();
    expect(".o_menuitem:eq(0)").toHaveClass("o_focused");

    // Same apps, new array: what a navigation hands down.
    parent.state.props = { ...base, apps: [...base.apps] };
    await animationFrame();
    expect(".o_menuitem:eq(0)").toHaveClass("o_focused", {
        message: "nothing about the grid changed, so the selection stands",
    });

    // A different app list is a different grid, and the index no longer means
    // what it meant.
    parent.state.props = { ...base, apps: base.apps.slice(0, 2) };
    await animationFrame();
    expect(".o_menuitem.o_focused").toHaveCount(0, {
        message: "the grid changed shape, so the selection is dropped",
    });
});

test("the grid scrolls to follow an arrow key, and stays put for anything else", async () => {
    // scrollIntoView used to run on every patch while a tile was selected, so
    // a badge provider answering -- or any unrelated render -- dragged the
    // grid back to a centred tile under a user who had scrolled away from it.
    let scrolls = 0;
    patchWithCleanup(Element.prototype, {
        scrollIntoView() {
            scrolls++;
        },
    });
    const apps = Array.from({ length: 12 }, (_, i) => ({
        actionID: 100 + i,
        href: `/odoo/action-${100 + i}`,
        appID: i + 1,
        id: i + 1,
        label: `App ${i}`,
        parents: "",
        webIcon: false,
        xmlid: `app${i}`,
    }));
    const homeMenu = await mountWithCleanup(HomeMenu, {
        props: { apps, reorderApps: (order) => reorderApps(apps, order) },
    });
    await animationFrame();

    scrolls = 0;
    await press("ArrowDown");
    await animationFrame();
    expect(scrolls).toBe(1, { message: "the arrow brings its tile into view" });

    await press("ArrowRight");
    await animationFrame();
    expect(scrolls).toBe(2);

    scrolls = 0;
    for (let i = 0; i < 3; i++) {
        homeMenu.render();
        await animationFrame();
    }
    expect(scrolls).toBe(0, {
        message: "renders that did not move the selection leave the scroll alone",
    });
    expect(".o_menuitem.o_focused").toHaveCount(1, {
        message: "and the selection itself is still there",
    });
});

test("an app is found by a word it is not named after", async () => {
    mockService("menu", { getMenuAsTree: () => EMPTY_TREE, selectMenu: () => {} });
    const apps = [
        {
            actionID: 121,
            href: "/odoo/action-121",
            appID: 1,
            id: 1,
            label: "Invoicing",
            parents: "",
            webIcon: false,
            xmlid: "app.1",
            module: "account",
            keywords: ["invoice", "vendor bill", "reconcile"],
            searchTerms: ["invoice", "vendor bill", "reconcile", "account"],
        },
        {
            actionID: 122,
            href: "/odoo/action-122",
            appID: 2,
            id: 2,
            label: "Inventory",
            parents: "",
            webIcon: false,
            xmlid: "app.2",
            module: "stock",
            models: ["stock.picking"],
            searchTerms: ["stock", "stock.picking"],
        },
    ];
    await mountWithCleanup(HomeMenu, {
        props: { apps, reorderApps: (o) => reorderApps(apps, o) },
    });
    const found = async (query) => {
        await searchFor(query);
        return queryAllTexts(".o_apps_listbox .o_caption");
    };
    expect(await found("invoice")).toEqual(["Invoicing"], {
        message: "a declared keyword",
    });
    expect(await found("reconcile")).toEqual(["Invoicing"]);
    expect(await found("account")).toEqual(["Invoicing"], { message: "the addon" });
    expect(await found("picking")).toEqual(["Inventory"], {
        message: "a model only this app opens",
    });
    expect(await found("invent")).toEqual(["Inventory"], {
        message: "the name still wins for its own prefix",
    });
});

test("a hidden app is decluttered from the grid, not hidden from the search", async () => {
    onRpc("set_res_users_settings", () => ({}));
    mockService("menu", { getMenuAsTree: () => EMPTY_TREE, selectMenu: () => {} });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps('{"hidden":["app.3"]}') });
    expect(queryAllTexts(".o_apps_listbox .o_caption")).toEqual([
        "Discuss",
        "Calendar",
    ]);

    await searchFor("cont");
    expect(queryAllTexts(".o_apps_listbox .o_caption")).toEqual(["Contacts"], {
        message: "asked for by name, so it is there",
    });
    expect(".o_app[data-menu-xmlid='app.3']").toHaveClass("o_app_hidden", {
        message: "and still says it is hidden",
    });

    await press("escape");
    await animationFrame();
    expect(queryAllTexts(".o_apps_listbox .o_caption")).toEqual([
        "Discuss",
        "Calendar",
    ]);
});

test("the grid takes category headings once it stops fitting on a screen", async () => {
    const make = (count) =>
        Array.from({ length: count }, (_, i) => ({
            actionID: 100 + i,
            href: `/odoo/action-${100 + i}`,
            appID: i + 1,
            id: i + 1,
            label: `App ${i}`,
            parents: "",
            webIcon: false,
            xmlid: `app.${i}`,
            category: i % 2 ? "Sales" : "Supply Chain",
        }));
    mockService("menu", { getMenuAsTree: () => EMPTY_TREE, selectMenu: () => {} });

    const thirteen = make(13);
    const big = await mountWithCleanup(HomeMenu, {
        props: { apps: thirteen, reorderApps: (o) => reorderApps(thirteen, o) },
    });
    expect(queryAllTexts(".o_apps_section .o_home_menu_section_title")).toEqual(
        ["SUPPLY CHAIN", "SALES"],
        { message: "in the order their first app sits in, not alphabetical" },
    );
    // The running index is the display order, so alt+n and the arrows agree
    // with what is on screen.
    expect(queryAllAttributes(".o_apps_section .o_app", "id").slice(0, 3)).toEqual([
        "result_app_0",
        "result_app_1",
        "result_app_2",
    ]);
    expect(
        big.appSections.map((section) => [
            section.category,
            section.offset,
            section.apps.map((app) => app.label),
        ]),
    ).toEqual([
        [
            "Supply Chain",
            0,
            ["App 0", "App 2", "App 4", "App 6", "App 8", "App 10", "App 12"],
        ],
        ["Sales", 7, ["App 1", "App 3", "App 5", "App 7", "App 9", "App 11"]],
    ]);

    await searchFor("app 1");
    expect(queryAllTexts(".o_apps_section .o_home_menu_section_title")).toEqual([], {
        message: "a query has its own order",
    });
});

test("a grid that fits on a screen is the overview, and takes no headings", async () => {
    const apps = Array.from({ length: 12 }, (_, i) => ({
        actionID: 100 + i,
        href: `/odoo/action-${100 + i}`,
        appID: i + 1,
        id: i + 1,
        label: `App ${i}`,
        parents: "",
        webIcon: false,
        xmlid: `app.${i}`,
        category: i % 2 ? "Sales" : "Supply Chain",
    }));
    mockService("menu", { getMenuAsTree: () => EMPTY_TREE, selectMenu: () => {} });
    const menu = await mountWithCleanup(HomeMenu, {
        props: { apps, reorderApps: (o) => reorderApps(apps, o) },
    });
    expect(".o_apps_section").toHaveCount(1);
    expect(queryAllTexts(".o_apps_section .o_home_menu_section_title")).toEqual([], {
        message: "a heading here would only cost a row",
    });
    expect(menu.appSections[0].offset).toBe(0);
});

test("the arrows walk the sections in the order they are shown", async () => {
    const apps = Array.from({ length: 14 }, (_, i) => ({
        actionID: 100 + i,
        href: `/odoo/action-${100 + i}`,
        appID: i + 1,
        id: i + 1,
        label: `App ${i}`,
        parents: "",
        webIcon: false,
        xmlid: `app.${i}`,
        category: i < 7 ? "Sales" : "Supply Chain",
    }));
    mockService("menu", { getMenuAsTree: () => EMPTY_TREE, selectMenu: () => {} });
    const menu = await mountWithCleanup(HomeMenu, {
        props: { apps, reorderApps: (o) => reorderApps(apps, o) },
    });
    // Sales holds seven, so it wraps after six; Supply Chain starts a row of
    // its own rather than filling the tail of the last Sales row.
    expect(menu.keyboardRows).toEqual([
        [0, 1, 2, 3, 4, 5],
        [6],
        [7, 8, 9, 10, 11, 12],
        [13],
    ]);
    expect(menu.visibleApps.map((app) => app.label)).toEqual(
        apps.map((app) => app.label),
    );
});

test("the launcher tells a screen reader what the query left on screen", async () => {
    mockService("menu", {
        getMenuAsTree: () => ({
            id: "root",
            name: "root",
            appID: "root",
            childrenTree: [
                {
                    id: 2,
                    name: "Calendar",
                    appID: 2,
                    actionID: 121,
                    childrenTree: [
                        {
                            id: 21,
                            name: "Calls",
                            appID: 2,
                            actionID: 123,
                            childrenTree: [],
                        },
                    ],
                },
            ],
        }),
        selectMenu: () => {},
    });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    expect(".o_home_menu_search_status").toHaveText("", {
        message: "nothing to say before a query",
    });
    expect(".o_home_menu_search_status").toHaveAttribute("aria-live", "polite");

    await searchFor("cal");
    expect(".o_home_menu_search_status").toHaveText("1 apps and 1 menus match");

    await searchFor("zzzz");
    expect(".o_home_menu_search_status").toHaveText("No apps or menus match");
});

test("three hovers over the navbar are one run of the providers", async () => {
    let calls = 0;
    registry.category("home_menu_badges").add("cached", {
        provide: () => {
            calls++;
            return { "app.1": calls };
        },
    });
    after(() => registry.category("home_menu_badges").remove("cached"));
    mockService("menu", {
        getMenuAsTree: () => ({
            id: "root",
            name: "root",
            appID: "root",
            childrenTree: [1, 2, 3].map((id) => ({
                id,
                name: `App ${id}`,
                appID: id,
                actionID: 120 + id,
                xmlid: `app.${id}`,
                childrenTree: [],
            })),
        }),
        selectMenu: () => {},
    });
    for (let i = 0; i < 3; i++) {
        await mountWithCleanup(QuickLauncher, { props: { close: () => {} } });
        await animationFrame();
    }
    expect(calls).toBe(1, {
        message: "the popover opens on a hover; it must not ask again on each one",
    });
    expect(".o_app_badge").toHaveText("1");
});

test("the counts are cached for a hover and re-read for a deliberate open", async () => {
    let calls = 0;
    registry.category("home_menu_badges").add("counted", {
        provide: () => {
            calls++;
            return {};
        },
    });
    after(() => registry.category("home_menu_badges").remove("counted"));
    const env = await makeMockEnv();
    const apps = [{ xmlid: "app.1" }, { xmlid: "app.2" }];

    await loadHomeMenuBadges(env, apps);
    await loadHomeMenuBadges(env, apps);
    expect(calls).toBe(1, { message: "a second reader inside the window joins" });

    await loadHomeMenuBadges(env, [...apps].reverse());
    expect(calls).toBe(1, {
        message: "the same apps in another order are the same question",
    });

    await loadHomeMenuBadges(env, [...apps, { xmlid: "app.3" }]);
    expect(calls).toBe(2, { message: "a different set is a different question" });

    await loadHomeMenuBadges(env, apps, { refresh: true });
    expect(calls).toBe(3, { message: "opening the launcher asks again" });
    await loadHomeMenuBadges(env, apps);
    expect(calls).toBe(3, { message: "and refills the cache behind it" });

    registry.category("home_menu_badges").add("late", { provide: () => ({}) });
    after(() => registry.category("home_menu_badges").remove("late"));
    await loadHomeMenuBadges(env, apps);
    expect(calls).toBe(4, {
        message:
            "a provider arriving means the cached answer was to a smaller question",
    });
});

test("the server's counts land on the tiles alongside a client provider's", async () => {
    onRpc("home.menu.badge", "get_badges", () => ({ "app.1": 4, "app.2": 1 }));
    registry.category("home_menu_badges").add("client_side", {
        provide: () => ({ "app.1": 3 }),
    });
    after(() => registry.category("home_menu_badges").remove("client_side"));
    mockService("menu", { getMenuAsTree: () => EMPTY_TREE, selectMenu: () => {} });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    await animationFrame();
    // Summed, not replaced: an addon counting from the store and one counting
    // from the database are both answering for the same tile.
    expect(".o_app[data-menu-xmlid='app.1'] .o_app_badge").toHaveText("7");
    expect(".o_app[data-menu-xmlid='app.2'] .o_app_badge").toHaveText("1");
    expect(".o_app[data-menu-xmlid='app.3'] .o_app_badge").toHaveCount(0);
});

test("the apps with something waiting lead the grid, most first", async () => {
    registry.category("home_menu_badges").add("attention", {
        provide: () => ({ "app.3": 2, "app.1": 40 }),
    });
    after(() => registry.category("home_menu_badges").remove("attention"));
    mockService("menu", { getMenuAsTree: () => EMPTY_TREE, selectMenu: () => {} });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    await animationFrame();
    // Ordered by what is waiting, not by the grid order or by use: the app with
    // forty is first even though it is neither pinned nor recently opened.
    expect(queryAllTexts(".o_attention_apps .o_caption")).toEqual([
        "Discuss",
        "Contacts",
    ]);
    expect(".o_attention_apps .o_app_badge:first").toHaveText("40");
    // Still in the grid below; the section is a shortcut, not a move.
    expect(queryAllTexts(".o_apps_listbox .o_caption")).toEqual([
        "Discuss",
        "Calendar",
        "Contacts",
    ]);

    await searchFor("cal");
    expect(".o_home_menu_attention").toHaveCount(0, {
        message: "a query has its own answer",
    });
});

test("no counts, no section", async () => {
    mockService("menu", { getMenuAsTree: () => EMPTY_TREE, selectMenu: () => {} });
    await mountWithCleanup(HomeMenu, { props: getLayoutProps() });
    await animationFrame();
    expect(".o_home_menu_attention").toHaveCount(0);

    await click(".o_home_menu_customize");
    await animationFrame();
    expect(".o_home_menu_attention").toHaveCount(0, {
        message: "and none while arranging the grid, where the tiles hide it anyway",
    });
});
