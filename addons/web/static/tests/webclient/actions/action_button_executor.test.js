// @ts-check

import { expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { user } from "@web/services/user";
import {
    buildCallButtonArgs,
    executeActionButton,
    filterActionContext,
    InvalidButtonParamsError,
} from "@web/webclient/actions/action_button_executor";

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
                effect: { add() {} },
            },
        },
        keepLast: { add: (prom) => prom },
        _loadAction: async () => ({ type: "ir.actions.act_window" }),
        doAction: async () => {},
        doActionButton: async () => {},
        _executeCloseAction: async () => {},
        ...overrides,
    };
    am.__ui = ui;
    return am;
}

// ── P03: block-ui overlay must always be released ──────────────────────────

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
    expect(am.__ui.count).toBe(0); // P03: a rejected RPC must not strand the overlay
});

test("block-ui: overlay is released on the embedded-action early return", async () => {
    // The embedded branch is gated on user settings pointing at an existing
    // embedded action; populate them locally (no RPC).
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
        expect(embeddedCalled).toBe(true); // took the embedded early-return path
        expect(am.__ui.count).toBe(0); // P03: the early return must still unblock
    } finally {
        user.updateUserSettings("embedded_actions_config_ids", {});
    }
});

test("block-ui: overlay is released when the RPC phase is superseded", async () => {
    // A03: a programmatic doAction firing while the button RPC is still in
    // flight bumps the shared (rejectSuperseded) KeepLast, so the button's
    // wrapper now REJECTS with a SupersededError instead of hanging forever.
    // executeActionButton lets it propagate — the `finally` still releases the
    // block-ui overlay, and the error service swallows the SupersededError.
    const keepLast = new KeepLast({ rejectSuperseded: true });
    const loadDef = new Deferred();
    const am = makeFakeAm({
        keepLast,
        _loadAction: () => loadDef,
    });
    const prom = executeActionButton(am, {
        name: 1,
        type: "action",
        "block-ui": "1",
    });
    await Promise.resolve();
    expect(am.__ui.blocked).toBe(1);
    expect(am.__ui.count).toBe(1); // overlay up while the RPC is pending

    // A newer task on the shared KeepLast supersedes the button task.
    keepLast.add(Promise.resolve());
    // The button's RPC still settles server-side afterwards.
    loadDef.resolve({ type: "ir.actions.act_window" });

    // The wrapper rejects with SupersededError; the overlay is still released.
    await expect(prom).rejects.toBeInstanceOf(SupersededError);
    expect(am.__ui.count).toBe(0); // the `finally` ran → overlay released
});

test("block-ui: overlay is released when the doAction phase is superseded", async () => {
    // A03: when the dispatched action is superseded before its controller
    // mounts, the action service rejects doAction's promise with a
    // SupersededError (ControllerComponent.onWillDestroy rejects the
    // currentActionProm). executeActionButton awaits doAction plainly now — the
    // `finally` releases the overlay and the rejection propagates to be
    // swallowed by the error service.
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
    expect(am.__ui.count).toBe(0); // the `finally` ran → overlay released
});

test("block-ui: the close flow runs when doAction resolves normally", async () => {
    // The non-superseded happy path: doAction resolves, so the post-doAction
    // close flow still runs and the overlay is released.
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

// ── P11: malformed object-button `args` must fail loudly, not silently ──────

test("args: an unparseable expression raises InvalidButtonParamsError (and unblocks)", async () => {
    const am = makeFakeAm();
    let error;
    try {
        await executeActionButton(am, {
            name: "act",
            type: "object",
            resModel: "res.partner",
            resId: 1,
            args: "[1, 2", // unterminated list → evaluateExpr throws
            "block-ui": "1",
        });
    } catch (e) {
        error = e;
    }
    expect(error).toBeInstanceOf(InvalidButtonParamsError);
    expect(am.__ui.count).toBe(0); // composes with P03's finally
});

test("args: a non-list value raises InvalidButtonParamsError", async () => {
    const am = makeFakeAm();
    await expect(
        executeActionButton(am, {
            name: "act",
            type: "object",
            resModel: "res.partner",
            resId: 1,
            args: "5", // valid expression, but not a list
        }),
    ).rejects.toThrow(/must evaluate to a list/);
});

// ── T2: extracted pure units (no fake am needed) ───────────────────────────

test("buildCallButtonArgs: record id(s) then the parsed args list", () => {
    expect(buildCallButtonArgs({ resId: 5 })).toEqual([[5]]);
    expect(buildCallButtonArgs({ resIds: [1, 2] })).toEqual([[1, 2]]);
    expect(buildCallButtonArgs({ resId: 5, name: "a", args: "[1, 'x']" })).toEqual([
        [5],
        1,
        "x",
    ]);
    // apostrophe inside a string round-trips (the L2 contract via evaluateExpr)
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
        // stripped (match CTX_KEY_REGEX):
        default_name: "x",
        search_default_partner_id: 1,
        show_address: true,
        form_view_ref: "m.v",
        group_by: ["state"],
        active_id: 1,
        active_ids: [1, 2],
        orderedBy: [{ name: "x" }],
        // kept:
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
