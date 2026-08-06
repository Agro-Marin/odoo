// @ts-check

import { after, expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import { user } from "@web/core/user";
import { SupersededError } from "@web/core/utils/concurrency";
import {
    buildCallButtonArgs,
    executeActionButton,
    filterActionContext,
    InvalidButtonParamsError,
} from "@web/webclient/actions/action_button_executor";
import { NavigationTracker } from "@web/webclient/actions/navigation_token";

/**
 * Build a fake ActionManager that counts ui.block/unblock calls and lets each
 * test stub the action-loading / dispatching seams executeActionButton uses.
 * `am.__ui.count` must return to 0 (balanced block/unblock); `am.__ui.blocked`
 * counts how many times the overlay was raised.
 * @param {Object} [overrides]
 * @returns {Object}
 */
function makeFakeAm(overrides = {}) {
    const ui = { count: 0, blocked: 0 };
    const am = {
        env: {
            bus: new EventBus(),
            services: {
                ui: {
                    block() {
                        ui.count++;
                        ui.blocked++;
                    },
                    unblock() {
                        ui.count--;
                    },
                },
                effect: {
                    add(effect) {
                        am.__effects.push(effect);
                    },
                },
            },
        },
        navigation: { guard: (prom) => prom },
        _loadAction: async () => ({ type: "ir.actions.act_window" }),
        doAction: async () => {},
        doActionButton: async () => {},
        _executeCloseAction: async () => {},
        ...overrides,
    };
    am.__ui = ui;
    am.__effects = [];
    return am;
}

test("block-ui: overlay is released after a successful action", async () => {
    const am = makeFakeAm();
    await executeActionButton(am, { name: 1, type: "action", "block-ui": "1" });
    expect(am.__ui.blocked).toBe(1);
    expect(am.__ui.count).toBe(0);
});

test("block-ui: overlay is released when the action load rejects", async () => {
    const am = makeFakeAm({
        _loadAction: async () => {
            throw new Error("load failed");
        },
    });
    await expect(
        executeActionButton(am, { name: 1, type: "action", "block-ui": "1" }),
    ).rejects.toThrow(/load failed/);
    expect(am.__ui.blocked).toBe(1);
    expect(am.__ui.count).toBe(0);
});

test("block-ui: overlay is released on the embedded-action early return", async () => {
    user.updateUserSettings("id", 1);
    user.updateUserSettings("embedded_actions_config_ids", {
        "7+1": { embedded_actions_order: [42] },
    });
    let embeddedCalled = false;
    const am = makeFakeAm({
        _loadAction: async () => ({
            id: 7,
            res_model: "res.partner",
            embedded_action_ids: [
                { id: 42, python_method: "do_thing", parent_res_model: "res.partner" },
            ],
        }),
        doActionButton: async () => {
            embeddedCalled = true;
        },
    });
    try {
        await executeActionButton(am, {
            name: 1,
            type: "action",
            resId: 1,
            "block-ui": "1",
        });
        expect(embeddedCalled).toBe(true);
        expect(am.__ui.count).toBe(0);
    } finally {
        user.updateUserSettings("embedded_actions_config_ids", {});
    }
});

test("block-ui: overlay is released when the RPC phase is superseded", async () => {
    const navigation = new NavigationTracker();
    const loadDef = new Deferred();
    const am = makeFakeAm({
        navigation,
        _loadAction: () => loadDef,
    });
    const prom = executeActionButton(am, {
        name: 1,
        type: "action",
        "block-ui": "1",
    });
    await Promise.resolve();
    expect(am.__ui.blocked).toBe(1);
    expect(am.__ui.count).toBe(1);

    navigation.guard(Promise.resolve());
    loadDef.resolve({ type: "ir.actions.act_window" });

    await expect(prom).rejects.toBeInstanceOf(SupersededError);
    expect(am.__ui.count).toBe(0);
});

test("block-ui: overlay is released when the doAction phase is superseded", async () => {
    const am = makeFakeAm({
        doAction: async () => {
            throw new SupersededError();
        },
    });
    const prom = executeActionButton(am, {
        name: 1,
        type: "action",
        "block-ui": "1",
    });
    await expect(prom).rejects.toBeInstanceOf(SupersededError);
    expect(am.__ui.count).toBe(0);
});

test("block-ui: the close flow runs when doAction resolves normally", async () => {
    let closed = false;
    const am = makeFakeAm({
        doAction: async () => {},
        _executeCloseAction: async () => {
            closed = true;
        },
    });
    await executeActionButton(am, {
        name: 1,
        type: "action",
        close: true,
        "block-ui": "1",
    });
    expect(closed).toBe(true);
    expect(am.__ui.count).toBe(0);
});

test("block-ui: overlay is released on a missing-type error", async () => {
    const am = makeFakeAm();
    await expect(executeActionButton(am, { name: 1, "block-ui": "1" })).rejects.toThrow(
        /Missing type/,
    );
    expect(am.__ui.count).toBe(0);
});

test("no block-ui: the overlay is never raised", async () => {
    const am = makeFakeAm();
    await executeActionButton(am, { name: 1, type: "action" });
    expect(am.__ui.blocked).toBe(0);
    expect(am.__ui.count).toBe(0);
});

test("args: an unparseable expression raises InvalidButtonParamsError (and unblocks)", async () => {
    const am = makeFakeAm();
    let error;
    try {
        await executeActionButton(am, {
            name: "act",
            type: "object",
            resModel: "res.partner",
            resId: 1,
            args: "[1, 2",
            "block-ui": "1",
        });
    } catch (e) {
        error = e;
    }
    expect(error).toBeInstanceOf(InvalidButtonParamsError);
    expect(am.__ui.count).toBe(0);
});

test("args: a non-list value raises InvalidButtonParamsError", async () => {
    const am = makeFakeAm();
    await expect(
        executeActionButton(am, {
            name: "act",
            type: "object",
            resModel: "res.partner",
            resId: 1,
            args: "5",
        }),
    ).rejects.toThrow(/must evaluate to a list/);
});

test("buildCallButtonArgs: record id(s) then the parsed args list", () => {
    expect(buildCallButtonArgs({ resId: 5 })).toEqual([[5]]);
    expect(buildCallButtonArgs({ resIds: [1, 2] })).toEqual([[1, 2]]);
    expect(buildCallButtonArgs({ resId: 5, name: "a", args: "[1, 'x']" })).toEqual([
        [5],
        1,
        "x",
    ]);
    expect(buildCallButtonArgs({ resId: 5, name: "a", args: `["it's"]` })).toEqual([
        [5],
        "it's",
    ]);
});

test("buildCallButtonArgs: an unparseable expression raises InvalidButtonParamsError", () => {
    let error;
    try {
        buildCallButtonArgs({ name: "a", resId: 1, args: "[1, 2" });
    } catch (e) {
        error = e;
    }
    expect(error).toBeInstanceOf(InvalidButtonParamsError);
});

test("buildCallButtonArgs: a non-list value is rejected with a descriptive error", () => {
    expect(() => buildCallButtonArgs({ name: "a", resId: 1, args: "5" })).toThrow(
        /must evaluate to a list/,
    );
});

test("filterActionContext: strips action-specific keys, keeps the rest", () => {
    const filtered = filterActionContext({
        default_name: "x",
        search_default_partner_id: 1,
        show_address: true,
        form_view_ref: "m.v",
        group_by: ["state"],
        active_id: 1,
        active_ids: [1, 2],
        orderedBy: [{ name: "x" }],
        lang: "en_US",
        active_model: "res.partner",
        uid: 2,
        my_custom_key: 7,
    });
    expect(filtered).toEqual({
        lang: "en_US",
        active_model: "res.partner",
        uid: 2,
        my_custom_key: 7,
    });
});

test("filterActionContext: tolerates an undefined context", () => {
    expect(filterActionContext(undefined)).toEqual({});
});

test("an embedded-action delegation still settles the click's obligations", async () => {
    // A view button on an action that carries embedded actions delegates the
    // whole click to the configured embedded one and returns early. That return
    // used to drop `onClose` — how `view_button_hook` reloads the view and how
    // `list_controller.openRecord` reloads its root — along with `close` and
    // `effect`, so the view sat on pre-action data with nothing left to
    // refresh it.
    const embedded = {
        id: 7,
        action_id: [99],
        parent_res_model: "partner",
        context: {},
    };
    const am = makeFakeAm({
        _loadAction: async () => ({
            type: "ir.actions.act_window",
            id: 5,
            embedded_action_ids: [embedded],
        }),
        doAction: async (_action, options) => {
            expect.step("doAction");
            await options?.onClose?.();
        },
        _executeCloseAction: async () => expect.step("closeAction"),
    });
    // The real manager routes this straight back into executeActionButton.
    am.doActionButton = (params, options) => executeActionButton(am, params, options);

    user.updateUserSettings("embedded_actions_config_ids", {
        "5+1": { embedded_actions_order: [7] },
    });
    after(() => user.updateUserSettings("embedded_actions_config_ids", {}));

    await executeActionButton(am, {
        name: 5,
        type: "action",
        resId: 1,
        resModel: "partner",
        close: true,
        effect: "{'type': 'rainbow_man'}",
        onClose: () => expect.step("onClose"),
    });

    expect.verifySteps(["doAction", "onClose", "closeAction"]);
    expect(am.__effects).toEqual([{ type: "rainbow_man" }]);
});

test("an embedded-action delegation matches the plain path's obligations", async () => {
    const am = makeFakeAm({
        _loadAction: async () => ({ type: "ir.actions.act_window", id: 5 }),
        doAction: async (_action, options) => {
            expect.step("doAction");
            await options?.onClose?.();
        },
        _executeCloseAction: async () => expect.step("closeAction"),
    });
    await executeActionButton(am, {
        name: 5,
        type: "action",
        resId: 1,
        resModel: "partner",
        close: true,
        effect: "{'type': 'rainbow_man'}",
        onClose: () => expect.step("onClose"),
    });
    expect.verifySteps(["doAction", "onClose", "closeAction"]);
    expect(am.__effects).toEqual([{ type: "rainbow_man" }]);
});
