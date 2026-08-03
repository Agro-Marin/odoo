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

/**
 * WHO RUNS WHEN A DIALOG CLOSES.
 *
 * A ``target: "new"`` action replaces whatever dialog is standing, and the
 * caller of the REPLACED action is still owed its ``onClose``. So the incoming
 * dialog inherits it -- ``stolenOnClose`` from the committed dialog,
 * ``supersededOnClose`` from a pending one it displaced -- and closing the last
 * dialog has to discharge every debt, in order, exactly once. A dialog that
 * never mounts has to hand the inherited ones BACK.
 *
 * ``action_dispatch.test.js`` pins the dialog SLOTS (which of `dialog` /
 * `nextDialog` holds what, after a commit, a discard or a failure). This pins
 * the callbacks those slots carry, which is the part a user notices: an
 * ``onClose`` that reloads a list, dropped or run twice.
 *
 * Asserted through ``doAction`` and the close action only -- never against
 * ``nextDialog.stolenOnClose`` and friends, which are the bookkeeping.
 */

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

/** A dialog action whose mount is held open until `def` resolves. */
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

/** A dialog action that throws on the way up. */
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
    // B's own first, then the one it took over.
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

    // Nothing is owed any more: a second close must not re-run them.
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

    // B is pending: it holds the `nextDialog` slot but has not mounted.
    const pending = action.doAction(slow, { onClose: step("B") });
    await animationFrame();

    // C displaces B before B could commit.
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

    // C displaces B and then dies on the way up. Its OWN onClose is not owed —
    // the action it belonged to never happened — but B's and A's still are, and
    // the dialog still standing is A.
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

    // B threw, A still ran, and the failure reached the caller of the close.
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
