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
import { reactive } from "@odoo/owl";
import { onRendered } from "@odoo/owl";
import {
    defineMenus,
    getService,
    mockService,
    mountWebClient,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { session } from "@web/session";
import { HomeMenu } from "@web/webclient/home_menu/home_menu";
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
    expect(homeMenu.defaultConfig.hidden).toEqual(["app.3"]);
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
    homeMenu.config.order = ["c", "a", "b"];
    await homeMenu._setCompanyDefault();
    await animationFrame();

    props.reorderApps(["b", "c", "a"]);
    homeMenu.config.order = ["b", "c", "a"];
    await animationFrame();
    expect(queryAllAttributes(".o_apps .o_app", "data-menu-xmlid")).toEqual([
        "b",
        "c",
        "a",
    ]);

    await homeMenu._resetLayout();
    await animationFrame();
    expect(homeMenu.config.order).toEqual(["c", "a", "b"]);
    expect(queryAllAttributes(".o_apps .o_app", "data-menu-xmlid")).toEqual(
        ["c", "a", "b"],
        { message: "the grid follows the company default the admin just set" },
    );
});

test("a keystroke evaluates each derived list once per render, not once per result row", async () => {
    // The matching-menu rows used to ask for the app grid's length one row at
    // a time, so eight rows rebuilt the pinned map and the fuzzy-matched list
    // eight times over, per render, per character typed.
    const counts = { shownApps: 0, pinnedApps: 0, unpinnedApps: 0, menuMatches: 0 };
    let renders = 0;
    class Counted extends HomeMenu {
        setup() {
            super.setup();
            onRendered(() => renders++);
        }
    }
    for (const name of Object.keys(counts)) {
        const desc = Object.getOwnPropertyDescriptor(HomeMenu.prototype, name);
        Object.defineProperty(Counted.prototype, name, {
            ...desc,
            get() {
                counts[name]++;
                return desc.get.call(this);
            },
        });
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
        expect(n).toBe(renders, { message: `${name}: once per render` });
    }
});
