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
        id: 3,
        xml_id: "action_3",
        name: "Dialog",
        res_model: "partner",
        target: "new",
        views: [[false, "form"]],
    },
]);

describe.current.tags("desktop");

function defineSlowDialog(/** @type {any} */ tag, /** @type {any} */ def) {
    class SlowDialog extends Component {
        static template = xml`<div class="slow_dialog"/>`;
        static props = ["*"];
        setup() {
            onWillStart(() => def);
        }
    }
    registry.category("actions").add(tag, SlowDialog);
    return { type: "ir.actions.client", tag, target: "new" };
}

function defineFailingDialog(/** @type {any} */ tag) {
    class FailingDialog extends Component {
        static template = xml`<div/>`;
        static props = ["*"];
        setup() {
            throw new Error("dialog boom");
        }
    }
    registry.category("actions").add(tag, FailingDialog);
    return { type: "ir.actions.client", tag, target: "new" };
}

const step = (/** @type {any} */ name) => () => expect.step(name);

async function closeDialog() {
    await getService("action").doAction({ type: "ir.actions.act_window_close" });
    await animationFrame();
}

test("a replacing dialog owes the replaced one's onClose too", async () => {
    await mountActionHost();
    const action = getService("action");

    await action.doAction(3, { onClose: step("A") });
    await animationFrame();
    await action.doAction(3, { onClose: step("B") });
    await animationFrame();

    expect.verifySteps([]);
    await closeDialog();
    expect.verifySteps(["B", "A"]);
});

test("closing discharges each inherited onClose exactly once", async () => {
    await mountActionHost();
    const action = getService("action");

    await action.doAction(3, { onClose: step("A") });
    await animationFrame();
    await action.doAction(3, { onClose: step("B") });
    await animationFrame();
    await closeDialog();
    expect.verifySteps(["B", "A"]);

    await closeDialog();
    expect.verifySteps([]);
});

test("a dialog superseded before mount still gets its onClose run by the winner", async () => {
    const block = new Deferred();
    const slow = defineSlowDialog("chain_slow_dialog", block);

    await mountActionHost();
    const action = getService("action");

    await action.doAction(3, { onClose: step("A") });
    await animationFrame();

    const pending = action.doAction(slow, { onClose: step("B") });
    await animationFrame();

    await action.doAction(3, { onClose: step("C") });
    await animationFrame();
    block.resolve();
    await pending;
    await animationFrame();

    expect.verifySteps([]);
    await closeDialog();
    expect.verifySteps(["C", "B", "A"]);
});

test("a dialog that never mounts hands the inherited onClose back", async () => {
    const block = new Deferred();
    const slow = defineSlowDialog("chain_slow_dialog_2", block);
    const failing = defineFailingDialog("chain_failing_dialog");

    await mountActionHost();
    const action = getService("action");

    await action.doAction(3, { onClose: step("A") });
    await animationFrame();
    const pending = action.doAction(slow, { onClose: step("B") });
    await animationFrame();

    const failure = await action.doAction(failing, { onClose: step("C") }).then(
        /** @returns {any} */ () => null,
        (/** @type {any} */ error) => error,
    );
    expect(failure).not.toBe(null);
    block.resolve();
    await pending;
    await animationFrame();

    expect(action.nextDialog).toBe(null);
    expect(action.dialog).not.toBe(null);
    expect.verifySteps([]);

    await closeDialog();
    expect.verifySteps(["B", "A"]);
});

test("an onClose that throws does not swallow the ones chained after it", async () => {
    await mountActionHost();
    const action = getService("action");

    await action.doAction(3, {
        onClose: () => {
            expect.step("A");
        },
    });
    await animationFrame();
    await action.doAction(3, {
        onClose: () => {
            expect.step("B");
            throw new Error("onClose boom");
        },
    });
    await animationFrame();

    const failure = await action.doAction({ type: "ir.actions.act_window_close" }).then(
        /** @returns {any} */ () => null,
        (/** @type {any} */ error) => error,
    );
    await animationFrame();

    expect.verifySteps(["B", "A"]);
    expect(failure?.message).toMatch(/onClose boom/);
});

test("two failing onClose callbacks are reported together", async () => {
    await mountActionHost();
    const action = getService("action");

    await action.doAction(3, {
        onClose: () => {
            throw new Error("A boom");
        },
    });
    await animationFrame();
    await action.doAction(3, {
        onClose: () => {
            throw new Error("B boom");
        },
    });
    await animationFrame();

    const failure = await action.doAction({ type: "ir.actions.act_window_close" }).then(
        /** @returns {any} */ () => null,
        (/** @type {any} */ error) => error,
    );
    await animationFrame();

    expect(failure).toBeInstanceOf(AggregateError);
    expect(failure.errors.map((/** @type {any} */ e) => e.message)).toEqual([
        "B boom",
        "A boom",
    ]);
});
