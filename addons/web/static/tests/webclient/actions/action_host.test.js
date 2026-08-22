// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineActions,
    defineModels,
    getService,
    models,
    mountActionHost,
    webModels,
} from "@web/../tests/web_test_helpers";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _rec_name = "display_name";
    _records = [{ id: 1, display_name: "First record" }];
    _views = {
        list: `<list><field name="display_name"/></list>`,
        form: `<form><field name="display_name"/></form>`,
        search: `<search/>`,
    };
}
defineModels([Partner, ResCompany, ResPartner, ResUsers]);

defineActions([
    {
        id: 1,
        xml_id: "action_1",
        name: "Partners",
        res_model: "partner",
        views: [
            [false, "list"],
            [false, "form"],
        ],
    },
    {
        id: 2,
        xml_id: "action_2",
        name: "Partner Dialog",
        res_model: "partner",
        target: "new",
        views: [[false, "form"]],
    },
]);

describe.current.tags("desktop");

test("doAction resolves and commits the stack with only the action container", async () => {
    await mountActionHost();
    const action = getService("action");
    expect(action.controllerStack).toHaveLength(0);

    await action.doAction(1);
    await animationFrame();

    expect(action.controllerStack).toHaveLength(1);
    expect(action.currentController.isMounted).toBe(true);
    expect(".o_action_manager .o_list_view").toHaveCount(1);
});

test("the dispatch promise is settled by the mount, not by doAction itself", async () => {
    await mountActionHost();
    const action = getService("action");
    let mountedAtResolution = null;
    await action
        .doAction(1)
        .then(() => (mountedAtResolution = action.currentController?.isMounted));
    expect(mountedAtResolution).toBe(true);
});

test("target='new' renders a dialog and commits the slot without a WebClient", async () => {
    await mountActionHost();
    const action = getService("action");

    await action.doAction(2);
    await animationFrame();

    expect(".o_technical_modal").toHaveCount(1);
    expect(action.dialog).not.toBe(null);
    expect(action.nextDialog).toBe(null);
    expect(action.controllerStack).toHaveLength(0);
});

test("act_window_close tears the dialog down and runs onClose once", async () => {
    await mountActionHost();
    const action = getService("action");

    await action.doAction(2, { onClose: () => expect.step("on_close") });
    await animationFrame();
    expect(".o_technical_modal").toHaveCount(1);
    expect.verifySteps([]);

    await action.doAction({ type: "ir.actions.act_window_close" });
    await animationFrame();

    expect(".o_technical_modal").toHaveCount(0);
    expect(action.dialog).toBe(null);
    expect.verifySteps(["on_close"]);
});

test("switchView works against a container-only host", async () => {
    await mountActionHost();
    const action = getService("action");

    await action.doAction(1);
    await animationFrame();
    expect(".o_list_view").toHaveCount(1);

    await action.switchView("form");
    await animationFrame();

    expect(".o_form_view").toHaveCount(1);
    expect(action.controllerStack).toHaveLength(2);
});
