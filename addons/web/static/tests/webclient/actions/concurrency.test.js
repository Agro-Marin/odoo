// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAll, queryAllTexts, runAllTimers } from "@odoo/hoot-dom";
import { animationFrame, Deferred, microTick } from "@odoo/hoot-mock";
import { Component, onWillStart, xml } from "@odoo/owl";
import {
    contains,
    defineActions,
    defineModels,
    fields,
    getService,
    isItemSelected,
    models,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
    serverState,
    stepAllNetworkCalls,
    switchView,
    toggleMenuItem,
    toggleSearchBarMenu,
    webModels,
} from "@web/../tests/web_test_helpers";
import { useSetupAction } from "@web/core/action_hook";
import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { SupersededError } from "@web/core/utils/concurrency";
import { redirect } from "@web/core/utils/urls";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { WebClient } from "@web/webclient/webclient";

const { ResCompany, ResPartner, ResUsers } = webModels;
const actionRegistry = registry.category("actions");

class Partner extends models.Model {
    _rec_name = "display_name";

    start = fields.Date();

    _records = [
        { id: 1, display_name: "First record" },
        { id: 2, display_name: "Second record" },
    ];
    _views = {
        form: /* xml */ `
            <form>
                <header>
                    <button name="object" string="Call method" type="object"/>
                </header>
                <group>
                    <field name="display_name"/>
                </group>
            </form>
        `,
        "kanban,1": /* xml */ `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="display_name"/>
                    </t>
                </templates>
            </kanban>`,
        list: /* xml */ `<list><field name="display_name"/></list>`,
        calendar: /* xml */ `<calendar date_start="start"/>`,
    };
}

class Pony extends models.Model {
    name = fields.Char();

    _records = [
        { id: 4, name: "Twilight Sparkle" },
        { id: 6, name: "Applejack" },
        { id: 9, name: "Fluttershy" },
    ];
    _views = {
        list: /* xml */ `<list><field name="name"/></list>`,
        form: /* xml */ `<form><field name="name"/></form>`,
    };
}

defineModels([Partner, Pony, ResCompany, ResPartner, ResUsers]);

defineActions([
    {
        id: 3,
        xml_id: "action_3",
        name: "Partners",
        res_model: "partner",
        views: [
            [false, "list"],
            [1, "kanban"],
            [false, "calendar"],
            [false, "form"],
        ],
    },
    {
        id: 4,
        xml_id: "action_4",
        name: "Partners Action 4",
        res_model: "partner",
        views: [
            [1, "kanban"],
            [false, "list"],
            [false, "form"],
        ],
    },
    {
        id: 5,
        xml_id: "action_5",
        name: "Create a Partner",
        res_model: "partner",
        target: "new",
        views: [[false, "form"]],
    },
    {
        id: 8,
        xml_id: "action_8",
        name: "Favorite Ponies",
        res_model: "pony",
        views: [
            [false, "list"],
            [false, "form"],
        ],
    },
]);

test("drop previous actions if possible", async () => {
    const def = new Deferred();
    stepAllNetworkCalls();
    onRpc("/web/action/load", () => def);

    await mountWithCleanup(WebClient);
    getService("action").doAction(4);
    getService("action").doAction(8);
    def.resolve();
    await animationFrame();
    // action 4 loads a kanban view first, 6 loads a list view. We want a list
    expect(".o_list_view").toHaveCount(1);
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
    ]);
});

test.tags("desktop");
test("handle switching view and switching back on slow network", async () => {
    const def = new Deferred();
    const defs = [null, def, null];
    stepAllNetworkCalls();
    onRpc("web_search_read", () => defs.shift());

    await mountWithCleanup(WebClient);
    await getService("action").doAction(4);
    // kanban view is loaded, switch to list view
    await switchView("list");
    // here, list view is not ready yet, because def is not resolved
    // switch back to kanban view
    await switchView("kanban");
    // here, we want the kanban view to reload itself, regardless of list view
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
        "web_search_read",
    ]);

    // we resolve def => list view is now ready (but we want to ignore it)
    def.resolve();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "there should be a kanban view in dom",
    });
    expect(".o_list_view").toHaveCount(0, {
        message: "there should not be a list view in dom",
    });
});

test.tags("desktop");
test("clicking quickly on breadcrumbs...", async () => {
    let def;
    onRpc("web_read", () => def);

    await mountWithCleanup(WebClient);
    // create a situation with 3 breadcrumbs: kanban/form/list
    await getService("action").doAction(4);
    await contains(".o_kanban_record").click();
    await getService("action").doAction(8);

    // block the form view reload's read
    def = new Deferred();
    // click the form breadcrumb, then the kanban one, before reload completes
    await contains(queryAll(".o_control_panel .breadcrumb-item")[1]).click();
    await contains(".o_control_panel .breadcrumb-item").click();

    // resolve the form view read
    def.resolve();
    await animationFrame();
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners Action 4",
    ]);
});

test.tags("desktop");
test("execute a new action while loading a lazy-loaded controller", async () => {
    defineActions([
        {
            id: 77,
            type: "ir.actions.act_window",
            res_model: "partner",
            views: [
                [false, "calendar"],
                [false, "form"],
            ],
        },
    ]);
    redirect("/odoo/action-77/2?cids=1");

    let def;
    onRpc("partner", "search_read", () => def);
    stepAllNetworkCalls();

    await mountWithCleanup(WebClient);
    await animationFrame(); // blank component
    expect(".o_form_view").toHaveCount(1, {
        message: "should display the form view of action 4",
    });

    // click to go back to Kanban (this request is blocked)
    def = new Deferred();
    await contains(".o_control_panel .breadcrumb a").click();
    expect(".o_form_view").toHaveCount(1, {
        message: "should still display the form view of action 4",
    });

    // execute another action meanwhile (don't block this request)
    await getService("action").doAction(8, { clearBreadcrumbs: true });
    expect(".o_list_view").toHaveCount(1, { message: "should display action 8" });
    expect(".o_form_view").toHaveCount(0, {
        message: "should no longer display the form view",
    });
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "web_read",
        "search_read",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
    ]);

    // unblock the switch to Kanban in action 4
    def.resolve();
    await animationFrame();
    expect(".o_list_view").toHaveCount(1, { message: "should still display action 8" });
    expect(".o_kanban_view").toHaveCount(0, {
        message: "should not display the kanban view of action 4",
    });
    expect.verifySteps([]);
});

test.tags("desktop");
test("execute a new action while handling a call_button", async () => {
    const def = new Deferred();
    onRpc("/web/dataset/call_button/*", async () => {
        await def;
        return {
            name: "Partners Action 1",
            res_model: "partner",
            views: [[1, "kanban"]],
        };
    });
    stepAllNetworkCalls();

    await mountWithCleanup(WebClient);
    // execute action 3 and open a record in form view
    await getService("action").doAction(3);
    await contains(".o_list_view .o_data_cell").click();
    expect(".o_form_view").toHaveCount(1, {
        message: "should display the form view of action 3",
    });

    // click on 'Call method' button (this request is blocked)
    await contains('.o_form_view button[name="object"]').click();
    expect(".o_form_view").toHaveCount(1, {
        message: "should still display the form view of action 3",
    });

    // execute another action
    await getService("action").doAction(8, { clearBreadcrumbs: true });
    expect(".o_list_view").toHaveCount(1, {
        message: "should display the list view of action 8",
    });
    expect(".o_form_view").toHaveCount(0, {
        message: "should no longer display the form view",
    });
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
        "web_read",
        "object",
        "/web/action/load",
        "get_views",
        "web_search_read",
    ]);

    // unblock the call_button request
    def.resolve();
    await animationFrame();
    expect(".o_list_view").toHaveCount(1, {
        message: "should still display the list view of action 8",
    });
    expect(".o_kanban_view").toHaveCount(0, { message: "should not display action 1" });
    expect.verifySteps([]);
});

test.tags("desktop");
test("execute a new action while switching to another controller", async () => {
    // doAction always has priority over a switch controller (clicking a row to
    // open the form view): the last actionManager operation wins. The form's
    // 'read' is superfluous but can land anywhere except after the final
    // action's 'search_read'.
    let def;
    stepAllNetworkCalls();
    onRpc("web_read", () => def);

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_list_view").toHaveCount(1, {
        message: "should display the list view of action 3",
    });

    // switch to the form view (this request is blocked)
    def = new Deferred();
    await contains(".o_list_view .o_data_cell").click();
    expect(".o_list_view").toHaveCount(1, {
        message: "should still display the list view of action 3",
    });

    // execute another action meanwhile (don't block this request)
    await getService("action").doAction(4, { clearBreadcrumbs: true });
    expect(".o_kanban_view").toHaveCount(1, {
        message: "should display the kanban view of action 8",
    });
    expect(".o_list_view").toHaveCount(0, {
        message: "should no longer display the list view",
    });
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
        "web_read",
        "/web/action/load",
        "get_views",
        "web_search_read",
    ]);

    // unblock the switch to the form view in action 3
    def.resolve();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "should still display the kanban view of action 8",
    });
    expect(".o_form_view").toHaveCount(0, {
        message: "should not display the form view of action 3",
    });
    expect.verifySteps([]);
});

test.tags("desktop");
test("a navigation blocked in clearUncommittedChanges can't mount over a newer one", async () => {
    // KeepLast guards only the load phase. If an action finishes loading, enters
    // its executor, and then blocks in clearUncommittedChanges (a save dialog
    // awaiting the user), a NEWER action can load and mount underneath it in the
    // meantime. When the save finally resolves, the earlier (now stale) action
    // must NOT mount on top of the newer one — the executor re-checks the
    // navigation generation after the await.
    await mountWithCleanup(WebClient);
    const am = getService("action");

    // Arm a one-shot slow clearUncommittedChanges: the first transition to ask
    // for consent blocks on ``saveDef`` (simulating an open save dialog).
    const saveDef = new Deferred();
    let armed = true;
    am.env.bus.addEventListener(AppEvent.CLEAR_UNCOMMITTED_CHANGES, (ev) => {
        if (armed) {
            armed = false;
            ev.detail.push(() => saveDef);
        }
    });

    // A: pony list — loads fully, then blocks in clearUncommittedChanges.
    const navA = am.doAction(8);
    await animationFrame();
    expect(".o_list_view").toHaveCount(0, {
        message: "A is blocked in clearUncommittedChanges, nothing mounted yet",
    });

    // B: partner kanban — newer navigation, its clearUncommittedChanges is
    // disarmed so it proceeds and mounts.
    await am.doAction(4);
    expect(".o_kanban_view").toHaveCount(1, { message: "newer action B is shown" });

    // Unblock A: it must abort instead of mounting over B.
    saveDef.resolve(true);
    await navA;
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "B (newer) is still shown after A unblocks",
    });
    expect(".o_list_view").toHaveCount(0, {
        message: "A (older, superseded) never mounted",
    });
});

test("execute a new action while loading views", async () => {
    const def = new Deferred();
    stepAllNetworkCalls();
    onRpc("get_views", () => def);

    await mountWithCleanup(WebClient);
    // execute a first action (its 'get_views' RPC is blocked)
    getService("action").doAction(3);
    await animationFrame();
    expect(".o_list_view").toHaveCount(0, {
        message: "should not display the list view of action 3",
    });

    // execute another action meanwhile (and unlock the RPC)
    getService("action").doAction(4);
    await animationFrame();
    def.resolve();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "should display the kanban view of action 4",
    });
    expect(".o_list_view").toHaveCount(0, {
        message: "should not display the list view of action 3",
    });
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners Action 4",
    ]);
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
    ]);
});

test.tags("desktop");
test("execute a new action while loading data of default view", async () => {
    const def = new Deferred();
    stepAllNetworkCalls();
    onRpc("web_read", () => def);

    await mountWithCleanup(WebClient);
    // execute a first action (its 'web_read' RPC is blocked)
    getService("action").doAction({
        name: "A Partner",
        res_model: "partner",
        res_id: 1,
        type: "ir.actions.act_window",
        views: [[false, "form"]],
    });
    await animationFrame();
    expect(".o_form_view").toHaveCount(0, {
        message: "should not display the form view",
    });

    // execute another action meanwhile (and unlock the RPC)
    getService("action").doAction(4);
    def.resolve();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "should display the kanban view of action 4",
    });
    expect(".o_form_view").toHaveCount(0, {
        message: "should not display the form view",
    });
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners Action 4",
    ]);
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "get_views",
        "web_read",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
    ]);
});

test.tags("desktop");
test("open a record while reloading the list view", async () => {
    let def;
    onRpc("search_read", () => def);

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_calendar_view").toHaveCount(0);
    expect(".o_list_view").toHaveCount(1);
    expect(".o_list_view .o_data_row").toHaveCount(2);
    expect(".o_control_panel .o_list_button_add").toHaveCount(1);

    // reload (the search_read RPC will be blocked)
    def = new Deferred();
    await switchView("calendar");
    expect(".o_list_view .o_data_row").toHaveCount(2);
    expect(".o_control_panel .o_list_button_add").toHaveCount(1);

    // open a record in form view
    await contains(".o_list_view .o_data_cell").click();
    expect(".o_form_view").toHaveCount(1);
    expect(".o_control_panel .o_list_button_add").toHaveCount(0);

    // unblock the search_read RPC
    def.resolve();
    await animationFrame();
    expect(".o_form_view").toHaveCount(1);
    expect(".o_list_view").toHaveCount(0);
    expect(".o_calendar_view").toHaveCount(0);
    expect(".o_control_panel .o_list_button_add").toHaveCount(0);
});

test("properly drop client actions after new action is initiated", async () => {
    const slowWillStartDef = new Deferred();
    class ClientAction extends Component {
        static template = xml`<div class="client_action">ClientAction</div>`;
        static props = ["*"];
        setup() {
            onWillStart(() => slowWillStartDef);
        }
    }
    actionRegistry.add("slowAction", ClientAction);

    await mountWithCleanup(WebClient);
    getService("action").doAction("slowAction");
    await animationFrame();
    expect(".client_action").toHaveCount(0, {
        message: "client action isn't ready yet",
    });

    getService("action").doAction(4);
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "should have loaded a kanban view",
    });

    slowWillStartDef.resolve();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "should still display the kanban view",
    });
});

test.tags("desktop");
test("restoring a controller when doing an action -- load_action slow", async () => {
    let def;
    onRpc("/web/action/load", () => def);
    stepAllNetworkCalls();

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_list_view").toHaveCount(1);

    await contains(".o_list_view .o_data_cell").click();
    expect(".o_form_view").toHaveCount(1);

    def = new Deferred();
    getService("action").doAction(4, { clearBreadcrumbs: true });
    await animationFrame();
    expect(".o_form_view").toHaveCount(1, {
        message: "should still contain the form view",
    });

    await contains(".o_control_panel .breadcrumb-item a").click();
    def.resolve();
    await animationFrame();
    expect(".o_list_view").toHaveCount(1);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
    ]);
    expect(".o_form_view").toHaveCount(0);
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
        "web_read",
        "/web/action/load",
        "web_search_read",
    ]);
});

test.tags("desktop");
test("switching when doing an action -- load_action slow", async () => {
    let def;
    onRpc("/web/action/load", () => def);
    stepAllNetworkCalls();

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_list_view").toHaveCount(1);

    def = new Deferred();
    getService("action").doAction(4, { clearBreadcrumbs: true });
    await animationFrame();
    expect(".o_list_view").toHaveCount(1, {
        message: "should still contain the list view",
    });

    await switchView("kanban");
    def.resolve();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
    ]);
    expect(".o_list_view").toHaveCount(0);
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
        "/web/action/load",
        "web_search_read",
    ]);
});

test.tags("desktop");
test("switching when doing an action -- get_views slow", async () => {
    let def;
    onRpc("get_views", () => def);
    stepAllNetworkCalls();

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_list_view").toHaveCount(1);

    def = new Deferred();
    getService("action").doAction(4);
    await animationFrame();
    expect(".o_list_view").toHaveCount(1, {
        message: "should still contain the list view",
    });

    await switchView("kanban");
    def.resolve();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
    ]);
    expect(".o_list_view").toHaveCount(0);
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
        "/web/action/load",
        "get_views",
        "web_search_read",
    ]);
});

test.tags("desktop");
test("switching when doing an action -- search_read slow", async () => {
    const def = new Deferred();
    onRpc("search_read", () => def);
    stepAllNetworkCalls();

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_list_view").toHaveCount(1);

    getService("action").doAction({
        type: "ir.actions.act_window",
        res_model: "partner",
        views: [[false, "calendar"]],
    });
    await animationFrame();
    await switchView("kanban");
    def.resolve();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
    ]);
    expect(".o_list_view").toHaveCount(0);
    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load",
        "get_views",
        "web_search_read",
        "has_group",
        "get_views",
        "search_read",
        "web_search_read",
    ]);
});

test.tags("desktop");
test("click multiple times to open a record", async () => {
    const def = new Deferred();
    onRpc("web_read", () => def);

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_list_view").toHaveCount(1);

    const row1 = queryAll(".o_list_view .o_data_row")[0];
    const row2 = queryAll(".o_list_view .o_data_row")[1];
    await contains(row1.querySelector(".o_data_cell")).click();
    await contains(row2.querySelector(".o_data_cell")).click();

    def.resolve();
    await animationFrame();
    expect(".o_form_view").toHaveCount(1);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
        "Second record",
    ]);
});

test("dialog will only open once for two rapid actions with the target new", async () => {
    const def = new Deferred();
    onRpc("onchange", () => def);

    await mountWithCleanup(WebClient);
    getService("action").doAction(5);
    await animationFrame();
    expect(".o_dialog .o_form_view").toHaveCount(0);

    getService("action").doAction(5);
    await animationFrame();
    expect(".o_dialog .o_form_view").toHaveCount(0);

    def.resolve();
    await animationFrame();
    expect(".o_dialog .o_form_view").toHaveCount(1);
});

test.tags("desktop");
test("local state, global state, and race conditions", async () => {
    patchWithCleanup(serverState.view_info, {
        toy: { multi_record: true, display_name: "Toy", icon: "fab fa-android" },
    });
    Partner._views = {
        toy: `<toy/>`,
        list: `<list><field name="display_name"/></list>`,
        search: `<search><filter name="display_name" string="Foo" domain="[]"/></search>`,
    };

    let def = Promise.resolve();
    let id = 1;
    class ToyController extends Component {
        static template = xml`
            <div class="o_toy_view">
                <ControlPanel />
                <SearchBar />
            </div>`;
        static components = { ControlPanel, SearchBar };
        static props = ["*"];
        setup() {
            this.id = id++;
            expect.step(this.props.state || "no state");
            useSetupAction({
                getLocalState: () => ({ fromId: this.id }),
            });
            onWillStart(() => def);
        }
    }

    registry.category("views").add("toy", {
        type: "toy",
        Controller: ToyController,
    });

    await mountWithCleanup(WebClient);

    await getService("action").doAction({
        res_model: "partner",
        type: "ir.actions.act_window",
        // list (or something else) must be added to have the view switcher displayed
        views: [
            [false, "toy"],
            [false, "list"],
        ],
    });

    await toggleSearchBarMenu();
    await toggleMenuItem("Foo");
    expect(isItemSelected("Foo")).toBe(true);

    // reload twice by clicking on toy view switcher
    def = new Deferred();
    await contains(".o_control_panel .o_switch_view.o_toy").click();
    await contains(".o_control_panel .o_switch_view.o_toy").click();

    def.resolve();
    await animationFrame();

    await toggleSearchBarMenu();
    expect(isItemSelected("Foo")).toBe(true);
    // Limitation: can't detect getGlobalState placement here, since
    // currentController.action.globalState always holds the first toy view's
    // search state regardless.

    expect.verifySteps([
        "no state", // setup first view instantiated
        { fromId: 1 }, // setup second view instantiated
        { fromId: 1 }, // setup third view instantiated
    ]);
});

test.tags("desktop");
test("doing browser back navigates to the previous action", async () => {
    // Previously this froze the page with `body.style.pointerEvents = "none"`
    // and thawed it via a race, to work around the action manager's KeepLast
    // never settling when the back-navigation load was superseded. That
    // workaround is gone: supersession now rejects observably (SupersededError,
    // swallowed by the error service), so the route change is a plain await.
    let def;
    onRpc("partner", "web_search_read", () => def);
    await mountWithCleanup(WebClient);

    await getService("action").doAction(4);
    await getService("action").doAction(8);
    await runAllTimers(); // wait for the update of the router
    expect(router.current).toEqual({
        action: 8,
        actionStack: [
            {
                action: 4,
                displayName: "Partners Action 4",
                view_type: "kanban",
            },
            {
                action: 8,
                displayName: "Favorite Ponies",
                view_type: "list",
            },
        ],
    });

    def = new Deferred();
    browser.history.back();
    // The page is no longer frozen while the back-navigation load is in flight.
    expect(document.body.style.pointerEvents).not.toBe("none");
    def.resolve();

    await animationFrame();
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners Action 4",
    ]);
});

test.tags("desktop");
test("superseded clearBreadcrumbs skeleton wait doesn't leave doAction pending", async () => {
    // Regression: while a `clearBreadcrumbs` doAction is parked on `await def`
    // waiting for its SkeletonView to mount, a newer `clearBreadcrumbs` doAction
    // fires ACTION_MANAGER:UPDATE and replaces (destroys-before-mount) that
    // skeleton. Its Deferred is resolved only from the skeleton's onMounted, so
    // without a supersession guard the superseded doAction promise would hang
    // forever. The guard rejects it with SupersededError (swallowed globally).
    class ClientActionA extends Component {
        static template = xml`<div class="client-a">A</div>`;
        static props = ["*"];
    }
    class ClientActionB extends Component {
        static template = xml`<div class="client-b">B</div>`;
        static props = ["*"];
    }
    actionRegistry.add("clientA", ClientActionA);
    actionRegistry.add("clientB", ClientActionB);

    await mountWithCleanup(WebClient);
    const action = getService("action");

    // Client actions have no RPC, so A reaches `await def` in pure microtasks.
    // Its SkeletonView only mounts on an animation frame — which we deliberately
    // withhold — so flushing microtasks parks A exactly at the skeleton wait.
    let aError = null;
    const promA = action.doAction("clientA", { clearBreadcrumbs: true }).then(
        () => expect.step("A resolved (unexpected)"),
        (err) => {
            aError = err;
        },
    );
    for (let i = 0; i < 50 && !action._skeletonDef; i++) {
        await microTick();
    }
    expect(Boolean(action._skeletonDef)).toBe(true);

    // A newer clearBreadcrumbs navigation supersedes the parked skeleton.
    action.doAction("clientB", { clearBreadcrumbs: true });
    // Without the fix this await never returns (defA never settles).
    await promA;
    expect(aError).toBeInstanceOf(SupersededError);

    // The winning navigation still lands normally.
    await animationFrame();
    await animationFrame();
    expect(".client-b").toHaveCount(1);
    expect(".client-a").toHaveCount(0);
    expect(action._skeletonDef).toBe(null);
    expect.verifySteps([]);
});
