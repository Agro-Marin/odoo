// @ts-check

import { expect, getFixture, test } from "@odoo/hoot";
import { queryOne, scroll, waitFor } from "@odoo/hoot-dom";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { Component, onWillStart, xml } from "@odoo/owl";
import {
    contains,
    defineActions,
    defineMenus,
    defineModels,
    fields,
    getDropdownMenu,
    getService,
    makeMockEnv,
    makeServerError,
    models,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
    serverState,
    stepAllNetworkCalls,
    switchView,
    webModels,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { redirect } from "@web/core/utils/urls";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { listView } from "@web/views/list/list_view";
import { PivotModel } from "@web/views/pivot/pivot_model";
import { WebClient } from "@web/webclient/webclient";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _rec_name = "display_name";

    o2m = fields.One2many({ relation: "partner", relation_field: "bar" });

    _records = [
        { id: 1, display_name: "First record", o2m: [2, 3] },
        {
            id: 2,
            display_name: "Second record",
            o2m: [1, 4, 5],
        },
        { id: 3, display_name: "Third record", o2m: [] },
        { id: 4, display_name: "Fourth record", o2m: [] },
        { id: 5, display_name: "Fifth record", o2m: [] },
    ];
    _views = {
        form: `
            <form>
                <header>
                    <button name="object" string="Call method" type="object"/>
                    <button name="4" string="Execute action" type="action"/>
                </header>
                <group>
                    <field name="display_name"/>
                </group>
            </form>`,
        "kanban,1": `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="display_name"/>
                    </t>
                </templates>
            </kanban>`,
        list: `<list><field name="display_name"/></list>`,
        "list,2": `<list limit="3"><field name="display_name"/></list>`,
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
        list: '<list><field name="name"/></list>',
        form: `<form><field name="name"/></form>`,
    };
}

defineModels([Partner, Pony, ResCompany, ResPartner, ResUsers]);

defineActions([
    {
        id: 1,
        xml_id: "action_1",
        name: "Partners Action 1",
        res_model: "partner",
        views: [[1, "kanban"]],
    },
    {
        id: 3,
        xml_id: "action_3",
        name: "Partners",
        res_model: "partner",
        views: [
            [false, "list"],
            [1, "kanban"],
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
        id: 4,
        xml_id: "action_4",
        name: "Partners Action 4",
        res_model: "partner",
        views: [
            [1, "kanban"],
            [2, "list"],
            [false, "form"],
        ],
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

const actionRegistry = registry.category("actions");
const actionHandlersRegistry = registry.category("action_handlers");

test("can execute actions from id, xmlid and tag", async () => {
    defineActions([
        {
            id: 10,
            tag: "client_action_by_db_id",
            target: "main",
            type: "ir.actions.client",
        },
        {
            id: 20,
            xml_id: "some_action",
            tag: "client_action_by_xml_id",
            target: "main",
            type: "ir.actions.client",
        },
        {
            id: 30,
            path: "my_action",
            tag: "client_action_by_path",
            target: "main",
            type: "ir.actions.client",
        },
    ]);
    actionRegistry
        .add("client_action_by_db_id", () => expect.step("client_action_db_id"))
        .add("client_action_by_xml_id", () => expect.step("client_action_xml_id"))
        .add("client_action_by_path", () => expect.step("client_action_path"))
        .add("client_action_by_tag", () => expect.step("client_action_tag"))
        .add("client_action_by_object", () => expect.step("client_action_object"));

    await makeMockEnv();
    await getService("action").doAction(10);
    expect.verifySteps(["client_action_db_id"]);
    await getService("action").doAction("some_action");
    expect.verifySteps(["client_action_xml_id"]);
    await getService("action").doAction("my_action");
    expect.verifySteps(["client_action_path"]);
    await getService("action").doAction("client_action_by_tag");
    expect.verifySteps(["client_action_tag"]);
    await getService("action").doAction({
        tag: "client_action_by_object",
        target: "current",
        type: "ir.actions.client",
    });
    expect.verifySteps(["client_action_object"]);
});

test("action doesn't exists", async () => {
    expect.assertions(1);
    await makeMockEnv();
    try {
        await getService("action").doAction({
            tag: "this_is_a_tag",
            target: "current",
            type: "ir.not_action.error",
        });
    } catch (e) {
        expect(e.message).toBe(
            "The ActionManager service can't handle actions of type ir.not_action.error",
        );
    }
});

test("getCurrentAction", async () => {
    await mountWithCleanup(WebClient);
    await getService("action").doAction(1);
    const currentAction = await getService("action").getCurrentAction();
    expect(currentAction).toEqual({
        binding_type: "action",
        binding_view_types: "list,form",
        id: 1,
        type: "ir.actions.act_window",
        xml_id: "action_1",
        name: "Partners Action 1",
        res_model: "partner",
        views: [[1, "kanban"]],
        context: {},
        embedded_action_ids: [],
        group_ids: [],
        limit: 80,
        mobile_view_mode: "kanban",
        target: "current",
        view_ids: [],
        view_mode: "list,form",
        cache: true,
    });
});

test("getCurrentAction (virtual controller)", async () => {
    stepAllNetworkCalls();
    class ClientAction extends Component {
        static template = xml`<div class="o_client_action_test">Hello World</div>`;
        static props = ["*"];
        static path = "plop";
        setup() {
            onWillStart(async () => {
                const currentAction = await getService("action").getCurrentAction();
                expect.step(currentAction);
            });
        }
    }
    actionRegistry.add("HelloWorldTest", ClientAction);

    redirect("/odoo/action-1/plop");
    await mountWithCleanup(WebClient);

    await animationFrame();

    expect.verifySteps([
        "/web/webclient/translations",
        "/web/webclient/load_menus",
        "/web/action/load_breadcrumbs",
        "/web/action/load",
        {
            binding_type: "action",
            binding_view_types: "list,form",
            id: 1,
            type: "ir.actions.act_window",
            xml_id: "action_1",
            name: "Partners Action 1",
            res_model: "partner",
            views: [[1, "kanban"]],
            context: {},
            embedded_action_ids: [],
            group_ids: [],
            limit: 80,
            mobile_view_mode: "kanban",
            target: "current",
            view_ids: [],
            view_mode: "list,form",
            cache: true,
        },
    ]);
});

test.tags("desktop");
test("restore to a deleted virtual action keeps the current controller and surfaces the error", async () => {
    redirect("/odoo/action-1/action-3");
    await mountWithCleanup(WebClient);
    await animationFrame();
    expect(".o_list_view").toHaveCount(1);

    const actionService = getService("action");
    const virtualController = actionService.controllerStack.find((c) => c.virtual);
    expect(virtualController).not.toBe(undefined);
    expect(virtualController.action.id).toBe(1);
    const currentBefore = actionService.currentController;
    const lengthBefore = actionService.controllerStack.length;

    onRpc("/web/action/load", async (request) => {
        const { params } = await request.json();
        if (params.action_id === 1) {
            throw makeServerError({
                errorName: "odoo.addons.web.controllers.action.MissingActionError",
                message: "Action does not exist",
            });
        }
    });

    await expect(actionService.restore(virtualController.jsId)).rejects.toThrow();

    expect(actionService.controllerStack).toHaveLength(lengthBefore);
    expect(actionService.currentController).toBe(currentBefore);
    expect(".o_list_view").toHaveCount(1);
});

test.tags("desktop");
test("restore to a virtual action whose view errors pre-mount keeps the displayed controller", async () => {
    expect.errors(1);
    redirect("/odoo/action-1/action-3");
    await mountWithCleanup(WebClient);
    await animationFrame();
    expect(".o_list_view").toHaveCount(1);

    const actionService = getService("action");
    const virtualController = actionService.controllerStack.find((c) => c.virtual);
    expect(virtualController.action.id).toBe(1);
    const currentBefore = actionService.currentController;
    const lengthBefore = actionService.controllerStack.length;

    patchWithCleanup(KanbanController.prototype, {
        setup() {
            super.setup();
            throw new Error("view failed to render");
        },
    });

    actionService.restore(virtualController.jsId);
    await animationFrame();
    await animationFrame();

    expect(".o_list_view").toHaveCount(1);
    expect(actionService.currentController).toBe(currentBefore);
    expect(actionService.controllerStack).toHaveLength(lengthBefore);
    expect.verifyErrors(["view failed to render"]);
});

test("action in handler registry", async () => {
    await makeMockEnv();
    actionHandlersRegistry.add("ir.action_in_handler_registry", ({ action }) =>
        expect.step(action.type),
    );
    await getService("action").doAction({
        tag: "this_is_a_tag",
        target: "current",
        type: "ir.action_in_handler_registry",
    });
    expect.verifySteps(["ir.action_in_handler_registry"]);
});

test("properly handle case when action id does not exist", async () => {
    expect.errors(1);
    await mountWithCleanup(WebClient);
    getService("action").doAction(4448);
    await waitFor(".o_error_dialog");
    expect.verifyErrors(["RPC_ERROR"]);
    expect(`.modal .o_error_dialog`).toHaveCount(1);
    expect(".o_error_dialog .modal-body").toHaveText("The action 4448 does not exist");
});

test("properly handle case when action path does not exist", async () => {
    expect.errors(1);
    await mountWithCleanup(WebClient);
    getService("action").doAction("plop");
    await waitFor(".o_error_dialog");
    expect.verifyErrors(["RPC_ERROR"]);
    expect(`.modal .o_error_dialog`).toHaveCount(1);
    expect(".o_error_dialog .modal-body").toHaveText(
        'The action "plop" does not exist',
    );
});

test("properly handle case when action xmlId does not exist", async () => {
    expect.errors(1);
    await mountWithCleanup(WebClient);
    getService("action").doAction("not.found.action");
    await waitFor(".o_error_dialog");
    expect.verifyErrors(["RPC_ERROR"]);
    expect(`.modal .o_error_dialog`).toHaveCount(1);
    expect(".o_error_dialog .modal-body").toHaveText(
        'The action "not.found.action" does not exist',
    );
});

test("actions can be cached", async () => {
    onRpc("/web/action/load", async (request) => {
        const { params } = await request.json();
        expect.step(params.context);
    });

    await makeMockEnv();

    await getService("action").loadAction(3);
    await getService("action").loadAction(3);

    await getService("action").loadAction(3, { configuratorMode: "add" });
    await getService("action").loadAction(3, { configuratorMode: "edit" });

    await getService("action").loadAction(3, { active_id: 1 });
    await getService("action").loadAction(3, { active_id: 1 });

    await getService("action").loadAction(3, { active_id: 2 });

    await getService("action").loadAction(3, { active_ids: [1, 2] });
    await getService("action").loadAction(3, { active_ids: [1, 2] });

    await getService("action").loadAction(3, { active_ids: [1, 2, 3] });

    await getService("action").loadAction(3, { active_model: "a" });
    await getService("action").loadAction(3, { active_model: "a" });

    await getService("action").loadAction(3, { active_model: "b" });

    const baseCtx = {
        lang: "en",
        tz: "taht",
        uid: 7,
        allowed_company_ids: [1],
    };
    expect.verifySteps([
        { ...baseCtx },
        { ...baseCtx, configuratorMode: "add" },
        { ...baseCtx, configuratorMode: "edit" },
        { ...baseCtx, active_id: 1 },
        { ...baseCtx, active_id: 2 },
        { ...baseCtx, active_ids: [1, 2] },
        { ...baseCtx, active_ids: [1, 2, 3] },
        { ...baseCtx, active_model: "a" },
        { ...baseCtx, active_model: "b" },
    ]);
});

test("action cache: additionalContext is used on the key", async () => {
    onRpc("/web/action/load", () => {
        expect.step("server loaded");
    });

    await makeMockEnv();
    const actionParams = {
        additionalContext: {
            some: { deep: { nested: "Robert" } },
        },
    };

    let action = await getService("action").loadAction(3, actionParams);
    expect.verifySteps(["server loaded"]);
    expect(action.context).toEqual(actionParams);

    action.context.additionalContext.some.deep.nested = "Nesta";

    actionParams.additionalContext.some.deep.nested = "Marley";
    action = await getService("action").loadAction(3, actionParams);
    expect.verifySteps(["server loaded"]);
    expect(action.context).toEqual(actionParams);
});

test.tags("desktop");
test('action with "no_breadcrumbs" set to true', async () => {
    defineActions([
        {
            id: 42,
            res_model: "partner",
            type: "ir.actions.act_window",
            views: [
                [1, "kanban"],
                [false, "list"],
            ],
            context: { no_breadcrumbs: true },
        },
    ]);
    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_breadcrumb").toHaveCount(1);
    await getService("action").doAction(42);
    await waitFor(".o_kanban_view");
    expect(".o_breadcrumb").toHaveCount(0);
    await contains(".o_switch_view.o_list").click();
    await waitFor(".o_list_view");
    expect(".o_breadcrumb").toHaveCount(0);
});

test("document's title is updated when an action is executed", async () => {
    await mountWithCleanup(WebClient);
    await animationFrame();
    let currentTitle = getService("title").getParts();
    expect(currentTitle).toEqual({});
    let currentState;
    await getService("action").doAction(4);
    await animationFrame();
    currentTitle = getService("title").getParts();
    expect(currentTitle).toEqual({ action: "Partners Action 4" });
    currentState = router.current;
    expect(currentState).toEqual({
        action: 4,
        actionStack: [
            {
                action: 4,
                displayName: "Partners Action 4",
                view_type: "kanban",
            },
        ],
    });

    await getService("action").doAction(8);
    await animationFrame();
    currentTitle = getService("title").getParts();
    expect(currentTitle).toEqual({ action: "Favorite Ponies" });
    currentState = router.current;
    expect(currentState).toEqual({
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

    await contains(".o_data_row .o_data_cell").click();
    await animationFrame();
    currentTitle = getService("title").getParts();
    expect(currentTitle).toEqual({ action: "Twilight Sparkle" });
    currentState = router.current;
    expect(currentState).toEqual({
        action: 8,
        resId: 4,
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
            {
                action: 8,
                resId: 4,
                displayName: "Twilight Sparkle",
                view_type: "form",
            },
        ],
    });
});

test.tags("desktop");
test('handles "history_back" event', async () => {
    let list;
    patchWithCleanup(listView.Controller.prototype, {
        setup() {
            super.setup(...arguments);
            list = this;
        },
    });
    await mountWithCleanup(WebClient);
    await getService("action").doAction(4);
    await getService("action").doAction(3);
    expect("ol.breadcrumb").toHaveCount(1);
    expect(".o_breadcrumb span").toHaveCount(1);
    list.env.config.historyBack();
    await animationFrame();
    expect(".o_breadcrumb span").toHaveCount(1);
    expect(".o_breadcrumb").toHaveText("Partners Action 4", {
        message: "breadcrumbs should display the display_name of the action",
    });
});

test.tags("desktop");
test("stores and restores scroll position (in kanban)", async () => {
    defineActions([
        {
            id: 10,
            name: "Partners",
            res_model: "partner",
            views: [[false, "kanban"]],
        },
    ]);
    for (let i = 0; i < 60; i++) {
        Partner._records.push({ id: 100 + i, display_name: `Record ${i}` });
    }
    const container = document.createElement("div");
    container.classList.add("o_web_client");
    container.style.height = "250px";
    getFixture().appendChild(container);
    await mountWithCleanup(WebClient, { target: container });
    await getService("action").doAction(10);
    expect(".o_content").toHaveProperty("scrollTop", 0);
    await scroll(".o_content", { top: 100 });
    await getService("action").doAction(4);
    expect(".o_content").toHaveProperty("scrollTop", 0);
    await contains(".o_control_panel .breadcrumb a").click();
    expect(".o_content").toHaveProperty("scrollTop", 100);
});

test.tags("desktop");
test("stores and restores scroll position (in list)", async () => {
    for (let i = 0; i < 60; i++) {
        Partner._records.push({ id: 100 + i, display_name: `Record ${i}` });
    }
    const container = document.createElement("div");
    container.classList.add("o_web_client");
    container.style.height = "250px";
    getFixture().appendChild(container);
    await mountWithCleanup(WebClient, { target: container });
    await getService("action").doAction(3);
    expect(".o_content").toHaveProperty("scrollTop", 0);
    expect(queryOne(".o_list_renderer").scrollTop).toBe(0);
    queryOne(".o_list_renderer").scrollTop = 100;
    await getService("action").doAction(4);
    expect(".o_content").toHaveProperty("scrollTop", 0);
    await contains(".o_control_panel .breadcrumb a").click();
    expect(".o_content").toHaveProperty("scrollTop", 0);
    expect(queryOne(".o_list_renderer").scrollTop).toBe(100);
});

test.tags("desktop");
test('executing an action with target != "new" closes all dialogs', async () => {
    Partner._views["form"] = `
        <form>
            <field name="o2m">
                <list><field name="display_name"/></list>
                <form><field name="display_name"/></form>
            </field>
        </form>`;
    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_list_view").toHaveCount(1);
    await contains(".o_list_view .o_data_row .o_list_char").click();
    expect(".o_form_view").toHaveCount(1);
    await contains(".o_form_view .o_data_row .o_data_cell").click();
    expect(".modal .o_form_view").toHaveCount(1);
    await getService("action").doAction(1);
    await animationFrame();
    expect(".modal").toHaveCount(0);
});

test.tags("desktop");
test('executing an action with target "new" does not close dialogs', async () => {
    Partner._views["form"] = `
        <form>
            <field name="o2m">
                <list><field name="display_name"/></list>
                <form><field name="display_name"/></form>
            </field>
        </form>`;
    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    expect(".o_list_view").toHaveCount(1);
    await contains(".o_list_view .o_data_row .o_data_cell").click();
    expect(".o_form_view").toHaveCount(1);
    await contains(".o_form_view .o_data_row .o_data_cell").click();
    expect(".modal .o_form_view").toHaveCount(1);
    await getService("action").doAction(5);
    expect(".modal .o_form_view").toHaveCount(2);
});

test.tags("desktop");
test("search defaults are removed from context when switching view", async () => {
    expect.assertions(1);
    const context = {
        search_default_x: true,
        searchpanel_default_y: true,
    };
    patchWithCleanup(PivotModel.prototype, {
        load(searchParams) {
            expect(searchParams.context).toEqual({
                allowed_company_ids: [1],
                lang: "en",
                tz: "taht",
                uid: 7,
            });
            return super.load(...arguments);
        },
    });

    await mountWithCleanup(WebClient);
    await getService("action").doAction({
        res_model: "partner",
        type: "ir.actions.act_window",
        views: [
            [false, "list"],
            [false, "pivot"],
        ],
        context,
    });
    await switchView("pivot");
});

test("retrieving a stored action should remove 'allowed_company_ids' from its context (model)", async () => {
    serverState.companies = [
        { id: 3, name: "Hermit", sequence: 1 },
        { id: 2, name: "Herman's", sequence: 2 },
        { id: 1, name: "Heroes TM", sequence: 3 },
    ];

    browser.sessionStorage.setItem(
        "current_action",
        JSON.stringify({
            id: 1,
            name: "Partners Action 1",
            res_model: "partner",
            type: "ir.actions.act_window",
            views: [[1, "kanban"]],
            context: {
                someKey: 44,
                allowed_company_ids: [1, 2],
                lang: "not_en",
                tz: "not_taht",
                uid: 42,
            },
        }),
    );

    Object.assign(browser.location, { search: "?model=partner&view_type=kanban" });

    await mountWithCleanup(WebClient);
    await animationFrame();

    expect(getService("action").currentController.action.context).toEqual({
        someKey: 44,
        lang: "not_en",
        tz: "not_taht",
        uid: 42,
    });
});

test("retrieving a stored action should remove 'allowed_company_ids' from its context (action)", async () => {
    serverState.companies = [
        { id: 3, name: "Hermit", sequence: 1 },
        { id: 2, name: "Herman's", sequence: 2 },
        { id: 1, name: "Heroes TM", sequence: 3 },
    ];

    browser.sessionStorage.setItem(
        "current_action",
        JSON.stringify({
            id: 1,
            name: "Partners Action 1",
            res_model: "partner",
            type: "ir.actions.act_window",
            views: [[1, "kanban"]],
            context: {
                someKey: 44,
                allowed_company_ids: [1, 2],
                lang: "not_en",
                tz: "not_taht",
                uid: 42,
            },
        }),
    );

    redirect("/odoo/action-1?view_type=kanban");

    await mountWithCleanup(WebClient);
    await animationFrame();

    expect(getService("action").currentController.action.context).toEqual({
        someKey: 44,
        lang: "not_en",
        tz: "not_taht",
        uid: 42,
    });
});
test.tags("desktop");
test("action is removed while waiting for another action with selectMenu", async () => {
    let def;
    class SlowClientAction extends Component {
        static template = xml`<div>My client action</div>`;
        static props = ["*"];

        setup() {
            onWillStart(() => def);
        }
    }
    actionRegistry.add("slow_client_action", SlowClientAction);
    defineActions([
        {
            id: 1001,
            tag: "slow_client_action",
            target: "main",
            type: "ir.actions.client",
            params: { description: "Id 1" },
        },
    ]);
    defineMenus([
        {
            id: 1,
            name: "App1",
            actionID: 1001,
            xmlid: "menu_1",
        },
    ]);

    await mountWithCleanup(WebClient);
    await animationFrame();
    await getService("action").doAction(4);
    expect(".o_kanban_view").toHaveCount(1);

    def = new Deferred();
    await contains(".o_navbar_apps_menu .dropdown-toggle").click();
    const appsMenu = getDropdownMenu(".o_navbar_apps_menu");
    await contains(".o_app:contains(App1)", { root: appsMenu }).click();

    expect(".o_action_manager").toHaveText("");

    def.resolve();
    await animationFrame();
    expect(".o_action_manager").toHaveText("My client action");
});

// Action 3 is a list+kanban window action, and mobile resolves it to the kanban
// view, so the list controller this reproduces the bug through never mounts.
test.tags("desktop");
test("_getView answers null — not a throw — when the tip is not a window action", async () => {
    // "no such view on this action" and "this action is not a window action at
    // all" are the same answer to the caller, and the two callers already know
    // what to do with it: switchView raises a typed ViewNotFoundError, and the
    // openFormView helper (a live view's selectRecord/createRecord prop) falls
    // through to opening a standalone form. The second case used to throw a
    // bare Error, so which one you got depended on WHY the view was missing —
    // and list_controller.openRecord awaits a save before calling selectRecord,
    // so a navigation landing in that window turned a row click into an
    // uncaught error.
    class PlainClientAction extends Component {
        static template = xml`<div class="plain_client_action"/>`;
        static props = ["*"];
    }
    registry.category("actions").add("plain_client_action", PlainClientAction);

    await mountWithCleanup(WebClient);
    const actionService = getService("action");
    await actionService.doAction(3);
    // The multi-record view the action opens with is preset-dependent (mobile
    // resolves `mobile_view_mode`), and irrelevant here: what matters is that a
    // window action is on the tip and exposes the prop captured below.
    expect(actionService.currentController.action.type).toBe("ir.actions.act_window");
    // Captured while the multi-record view is on top, exactly as openRecord()
    // holds it across its `await record.save()`.
    const selectRecord = actionService.currentController.props.selectRecord;

    await actionService.doAction({
        type: "ir.actions.client",
        tag: "plain_client_action",
    });
    expect(".plain_client_action").toHaveCount(1);
    expect(actionService.currentController.action.type).toBe("ir.actions.client");

    expect(actionService._getView("form")).toBe(null);
    // No throw: the stale closure degrades to a no-op instead of an error dialog.
    await selectRecord(1, {});
    expect(".plain_client_action").toHaveCount(1);
});

test("a handler registered for a built-in action type is reported as dead", async () => {
    // `action_handlers` is the extension point for NEW types; the six the
    // service implements itself always win. Registering against one of them
    // looks like it took effect and never runs.
    patchWithCleanup(odoo, { debug: "1" });
    patchWithCleanup(console, {
        warn: (message) => expect.step(message),
    });
    actionHandlersRegistry.add("ir.actions.act_window_close", () =>
        expect.step("never-runs"),
    );

    await mountWithCleanup(WebClient);
    await getService("action").doAction({ type: "ir.actions.act_window_close" });

    expect.verifySteps([
        `[action] "ir.actions.act_window_close" is dispatched by the action service itself; the "action_handlers" entry registered for it will never run.`,
    ]);
});

test("an onClose dropped by an inline dispatch is reported in debug", async () => {
    // `onClose` only ever fires for dialogs; an inline (non-dialog) dispatch
    // silently ignores it. In debug, say so instead.
    patchWithCleanup(odoo, { debug: "1" });
    patchWithCleanup(console, {
        warn: (message) => expect.step(message),
    });
    await mountWithCleanup(WebClient);
    await getService("action").doAction(1, { onClose: () => {} });
    expect.verifySteps([
        `[action] "onClose" is ignored for inline dispatches: action "1" does not open a dialog.`,
    ]);
    // A dialog dispatch keeps its onClose: no warning.
    await getService("action").doAction(5, { onClose: () => {} });
    expect.verifySteps([]);
});

test("ACTION_MANAGER:SETTLED fires for an action that changes nothing on screen", async () => {
    // The signal exists for exactly this case: a server action returning
    // nothing pushes no UI update, so anything waiting on the visible effect
    // waits forever. `clickbot` is the caller that used to.
    //
    // Once, though: the server action becomes an act_window_close, which
    // re-enters `doAction`. Announcing from every level told a waiter the
    // dispatch was over while the outer one was still running.
    onRpc("/web/action/run", () => false);
    await mountWithCleanup(WebClient);
    await getService("action").doAction(1);

    let settled = 0;
    getService("action").env.bus.addEventListener(
        AppEvent.ACTION_MANAGER_SETTLED,
        () => settled++,
    );
    const uiUpdates = [];
    getService("action").env.bus.addEventListener(
        AppEvent.ACTION_MANAGER_UI_UPDATED,
        () => uiUpdates.push(1),
    );

    await getService("action").doAction({ type: "ir.actions.server", id: 99 });

    expect(settled).toBe(1, {
        message: "one gesture, however many actions it decomposes into",
    });
    expect(uiUpdates).toEqual([], { message: "nothing changed on screen" });
});

test("ACTION_MANAGER:SETTLED fires even when the dispatch fails", async () => {
    // A waiter told only about successes hangs on the cases worth noticing.
    await mountWithCleanup(WebClient);
    let settled = 0;
    getService("action").env.bus.addEventListener(
        AppEvent.ACTION_MANAGER_SETTLED,
        () => settled++,
    );
    await expect(
        getService("action").doAction({ type: "ir.actions.does_not_exist" }),
    ).rejects.toThrow();
    expect(settled).toBe(1);
});
