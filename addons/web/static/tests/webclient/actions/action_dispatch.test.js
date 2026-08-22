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
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _rec_name = "display_name";
    _records = [
        { id: 1, display_name: "First record" },
        { id: 2, display_name: "Second record" },
    ];
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
        name: "Partners 2",
        res_model: "partner",
        views: [
            [false, "list"],
            [false, "form"],
        ],
    },
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

test("commit replaces the stack wholesale, it does not mutate it in place", async () => {
    await mountActionHost();
    const action = getService("action");
    await action.doAction(1);
    await animationFrame();
    const stackAfterFirst = action.controllerStack;
    expect(stackAfterFirst).toHaveLength(1);

    await action.doAction(2);
    await animationFrame();

    expect(action.controllerStack).not.toBe(stackAfterFirst);
    expect(stackAfterFirst).toHaveLength(1);
    expect(action.controllerStack).toHaveLength(2);
});

test("the stack is already committed when the doAction promise resolves", async () => {
    await mountActionHost();
    const action = getService("action");
    let lengthAtResolution = null;
    let mountedAtResolution = null;
    await action.doAction(1).then(() => {
        lengthAtResolution = action.controllerStack.length;
        mountedAtResolution = action.controllerStack.at(-1)?.isMounted;
    });
    expect(lengthAtResolution).toBe(1);
    expect(mountedAtResolution).toBe(true);
});

test("UI_UPDATED is emitted after the stack is committed", async () => {
    await mountActionHost();
    const action = getService("action");
    let lengthAtEvent = null;
    action.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UI_UPDATED, () => {
        lengthAtEvent ??= action.controllerStack.length;
    });
    await action.doAction(1);
    await animationFrame();
    expect(lengthAtEvent).toBe(1);
});

test("committing a dialog promotes the pending slot and empties it", async () => {
    await mountActionHost();
    const action = getService("action");
    await action.doAction(3);
    await animationFrame();

    expect(action.dialog).not.toBe(null);
    expect(action.nextDialog).toBe(null);
    expect(action.controllerStack).toHaveLength(0);
});

test("a replacement dialog promotes over the previous one, leaving one committed", async () => {
    await mountActionHost();
    const action = getService("action");
    await action.doAction(3);
    await animationFrame();
    const firstDialog = action.dialog;

    await action.doAction(3);
    await animationFrame();

    expect(action.dialog).not.toBe(firstDialog);
    expect(action.nextDialog).toBe(null);
    expect(".o_technical_modal").toHaveCount(1);
});

test("a dispatch destroyed before mount settles (does not hang) and commits nothing", async () => {
    const def = new Deferred();
    class SlowAction extends Component {
        static template = xml`<div class="slow_action"/>`;
        static props = ["*"];
        setup() {
            onWillStart(() => def);
        }
    }
    registry.category("actions").add("slow_dispatch_action", SlowAction);

    await mountActionHost();
    const action = getService("action");
    await action.doAction(1);
    await animationFrame();
    const committed = action.controllerStack;

    const superseded = action.doAction({
        type: "ir.actions.client",
        tag: "slow_dispatch_action",
    });
    await animationFrame();
    await action.doAction(2);
    await animationFrame();
    def.resolve();

    expect(await superseded).toBe(undefined);
    expect(action.controllerStack).not.toBe(committed);
    expect(action.controllerStack.at(-1).action.id).toBe(2);
});

test("a dialog dispatch destroyed before mount resolves quietly, like the inline path", async () => {
    const def = new Deferred();
    class SlowDialog extends Component {
        static template = xml`<div class="slow_dialog"/>`;
        static props = ["*"];
        setup() {
            onWillStart(() => def);
        }
    }
    registry.category("actions").add("slow_dispatch_dialog", SlowDialog);

    await mountActionHost();
    const action = getService("action");

    const superseded = action.doAction({
        type: "ir.actions.client",
        tag: "slow_dispatch_dialog",
        target: "new",
    });
    let rejection = null;
    superseded.catch((error) => (rejection = error));
    await animationFrame();
    await action.doAction(3);
    await animationFrame();
    def.resolve();

    expect(await superseded).toBe(undefined);
    expect(rejection).toBe(null);
    expect(action.nextDialog).toBe(null);
});

test("a controller that throws before mounting never commits its stack", async () => {
    class FailingAction extends Component {
        static template = xml`<div/>`;
        static props = ["*"];
        setup() {
            throw new Error("boom");
        }
    }
    registry.category("actions").add("failing_dispatch_action", FailingAction);

    await mountActionHost();
    const action = getService("action");
    await action.doAction(1);
    await animationFrame();
    const committed = action.controllerStack;
    expect(committed).toHaveLength(1);

    const failure = await action
        .doAction({ type: "ir.actions.client", tag: "failing_dispatch_action" })
        .then(
            () => null,
            (error) => error,
        );
    expect(failure).not.toBe(null);
    expect(failure.cause?.message ?? failure.message).toMatch(/boom/);
    await animationFrame();

    expect(action.controllerStack).toHaveLength(1);
    expect(action.controllerStack.at(-1)).toBe(committed.at(-1));
});

test("a failed dialog replacement leaves exactly one committed dialog", async () => {
    class FailingDialog extends Component {
        static template = xml`<div/>`;
        static props = ["*"];
        setup() {
            throw new Error("dialog boom");
        }
    }
    registry.category("actions").add("failing_dispatch_dialog", FailingDialog);

    await mountActionHost();
    const action = getService("action");
    await action.doAction(3, { onClose: () => expect.step("committed on_close") });
    await animationFrame();
    const committedDialog = action.dialog;

    const failure = await action
        .doAction({
            type: "ir.actions.client",
            tag: "failing_dispatch_dialog",
            target: "new",
        })
        .then(
            () => null,
            (error) => error,
        );
    expect(failure).not.toBe(null);
    expect(failure.cause?.message ?? failure.message).toMatch(/dialog boom/);
    await animationFrame();

    expect(action.nextDialog).toBe(null);
    expect(action.dialog).toBe(committedDialog);
    expect(typeof action.dialog.onClose).toBe("function");
    expect.verifySteps([]);

    await action.doAction({ type: "ir.actions.act_window_close" });
    expect.verifySteps(["committed on_close"]);
});

test("a proposed stack is not installed while the dispatch is in flight", async () => {
    const blockLeaf = new Deferred();
    let loads = 0;
    class Slow extends Component {
        static template = xml`<div class="o_slow"/>`;
        static props = ["*"];
        setup() {
            onWillStart(async () => {
                if (loads++) {
                    await blockLeaf;
                }
            });
        }
    }
    registry.category("actions").add("slow_dispatch", Slow);

    await mountActionHost();
    const action = getService("action");
    await action.doAction({ type: "ir.actions.client", tag: "slow_dispatch" });
    const mountedStack = action.controllerStack;
    expect(mountedStack).toHaveLength(1);

    const ancestor = { jsId: "ancestor", action: { jsId: "a0" }, props: {} };
    const inFlight = action.doAction(
        { type: "ir.actions.client", tag: "slow_dispatch" },
        { newStack: [ancestor] },
    );
    await animationFrame();

    expect(action.controllerStack).toBe(mountedStack);

    blockLeaf.resolve();
    await inFlight;
    await animationFrame();

    expect(action.controllerStack.at(0)).toBe(ancestor);
    expect(action.controllerStack).toHaveLength(2);
});
