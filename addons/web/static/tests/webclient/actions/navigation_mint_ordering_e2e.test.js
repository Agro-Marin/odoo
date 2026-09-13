// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import {
    contains,
    defineActions,
    defineModels,
    fields,
    getService,
    models,
    mountWebClient,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _rec_name = "display_name";
    display_name = fields.Char();
    _records = [{ id: 1, display_name: "First" }];
    _views = {
        list: `<list><field name="display_name"/></list>`,
        kanban: `<kanban><templates><t t-name="card"><field name="display_name"/></t></templates></kanban>`,
        form: `<form><field name="display_name"/></form>`,
        search: `<search/>`,
    };
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

defineActions([
    {
        id: 21,
        xml_id: "a21",
        name: "List",
        res_model: "partner",
        views: [
            [false, "list"],
            [false, "form"],
        ],
    },
    {
        id: 22,
        xml_id: "a22",
        name: "Kanban",
        res_model: "partner",
        views: [
            [false, "kanban"],
            [false, "form"],
        ],
    },
    {
        id: 23,
        xml_id: "a23",
        name: "Dialog",
        res_model: "partner",
        target: "new",
        views: [[false, "form"]],
    },
]);

function holdNextActionLoad() {
    const held = new Deferred();
    let holding = false;
    onRpc("/web/action/load", async () => {
        if (holding) {
            await held;
        }
    });
    return {
        start: () => (holding = true),
        release: () => held.resolve(),
    };
}

test("a switchView refused by an open dialog does not lose the pending navigation", async () => {
    await mountWebClient();
    const action = getService("action");
    await action.doAction(21);
    await action.doAction(23);
    await animationFrame();
    expect(".modal").toHaveCount(1);

    const load = holdNextActionLoad();
    load.start();
    let outcome = "pending";
    const navigation = action.doAction(22).then(
        () => (outcome = "resolved"),
        (error) => (outcome = `rejected:${error.constructor.name}`),
    );
    await animationFrame();

    await action.switchView("form");
    load.release();
    await navigation;
    await animationFrame();

    expect(outcome).toBe("resolved");
});

test("a switchView refused by a pending dispatch does not lose the pending navigation", async () => {
    await mountWebClient();
    const action = getService("action");
    await action.doAction(21);
    action._pendingDispatch = /** @type {any} */ ({
        baseStack: action.controllerStack,
    });

    const load = holdNextActionLoad();
    load.start();
    let outcome = "pending";
    const navigation = action.doAction(22).then(
        () => (outcome = "resolved"),
        (error) => (outcome = `rejected:${error.constructor.name}`),
    );
    await animationFrame();

    await action.switchView("form");
    load.release();
    await navigation;
    await animationFrame();

    expect(outcome).toBe("resolved");
});

test("a record clicked while a dispatch is pending is resolved against the mounted list, and the click is dropped", async () => {
    await mountWebClient();
    const action = getService("action");
    await action.doAction(21);
    expect(".o_list_view").toHaveCount(1);
    action._pendingDispatch = /** @type {any} */ ({ baseStack: [] });
    expect(action.currentController).toBe(null, {
        message: "currentController follows the pending dispatch's base stack",
    });
    expect(action.getView("form")?.type).toBe("form", {
        message: "getView follows the mounted stack, which is what the click came from",
    });
    await contains(".o_data_row .o_data_cell").click();
    await animationFrame();
    expect(".o_list_view").toHaveCount(1);
    expect(".o_form_view").toHaveCount(0);
    action._pendingDispatch = null;
    await contains(".o_data_row .o_data_cell").click();
    await animationFrame();
    expect(".o_form_view").toHaveCount(1);
});
