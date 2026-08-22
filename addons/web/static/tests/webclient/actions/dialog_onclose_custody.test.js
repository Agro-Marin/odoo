// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { Component, onWillStart, xml } from "@odoo/owl";
import {
    defineActions,
    defineModels,
    getService,
    models,
    mountActionHost,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

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
        name: "Dialog A",
        res_model: "partner",
        target: "new",
        type: "ir.actions.act_window",
        views: [[false, "form"]],
    },
]);

describe.current.tags("desktop");

function slowDialog(/** @type {string} */ tag) {
    const def = new Deferred();
    class SlowDialog extends Component {
        static template = xml`<div class="slow_dialog"/>`;
        static props = ["*"];
        setup() {
            onWillStart(() => def);
        }
    }
    registry.category("actions").add(tag, SlowDialog);
    return def;
}

test("a pending dialog that dies hands the stolen onClose back to A", async () => {
    const def = slowDialog("probe_dialog_1");
    await mountActionHost();
    const action = getService("action");
    /** @type {string[]} */
    const calls = [];

    await action.doAction(1, { onClose: () => calls.push("A") });
    await animationFrame();

    const pending = action.doAction(
        { type: "ir.actions.client", tag: "probe_dialog_1", target: "new" },
        { onClose: () => calls.push("B") },
    );
    await animationFrame();

    def.reject(new Error("B never mounts"));
    await pending.catch(() => {});
    await animationFrame();

    await action.doAction({ type: "ir.actions.act_window_close" });
    await animationFrame();
    expect(calls).toEqual(["A"]);
});

test("when B commits it adopts the stolen onClose and runs it on close", async () => {
    const def = slowDialog("probe_dialog_2");
    await mountActionHost();
    const action = getService("action");
    /** @type {string[]} */
    const calls = [];

    await action.doAction(1, { onClose: () => calls.push("A") });
    await animationFrame();

    const pending = action.doAction(
        { type: "ir.actions.client", tag: "probe_dialog_2", target: "new" },
        { onClose: () => calls.push("B") },
    );
    await animationFrame();

    await action.doAction({ type: "ir.actions.act_window_close" });
    await animationFrame();

    def.resolve();
    await pending;
    await animationFrame();
    expect(calls).toEqual([]);

    await action.doAction({ type: "ir.actions.act_window_close" });
    await animationFrame();
    expect(calls).toEqual(["B", "A"]);
});

test("a pending dialog that never mounts does not swallow the stolen onClose", async () => {
    const def = slowDialog("probe_dialog_3");
    await mountActionHost();
    const action = getService("action");
    /** @type {string[]} */
    const calls = [];

    await action.doAction(1, { onClose: () => calls.push("A") });
    await animationFrame();

    const pending = action.doAction(
        { type: "ir.actions.client", tag: "probe_dialog_3", target: "new" },
        { onClose: () => calls.push("B") },
    );
    await animationFrame();

    await action.doAction({ type: "ir.actions.act_window_close" });
    await animationFrame();
    expect(calls).toEqual([]);

    def.reject(new Error("B never mounts"));
    await pending.catch(() => {});
    await animationFrame();
    await animationFrame();

    expect(calls).toEqual(["A"]);
});
