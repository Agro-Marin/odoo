// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { executeActWindowAction } from "@web/webclient/actions/action_executors/act_window";

/**
 * @param {Object} [overrides]
 */
function makeFakeAm(overrides = {}) {
    /** @type {Record<string, any[]>} */
    const calls = { updateUI: [], confirmLeave: [] };
    const am = {
        env: { isSmall: false },
        _confirmLeave: async (opts) => {
            calls.confirmLeave.push(opts);
            return true;
        },
        _makeController: (params) => ({ jsId: "controller_1", ...params }),
        _getViewInfo: (view, action, views, props) => ({
            props: { ...props, type: view.type },
        }),
        _updateUI: async (controller, options) => {
            calls.updateUI.push({ controller, options });
            return "updateUI-result";
        },
        ...overrides,
    };
    am.__calls = calls;
    return am;
}

/** @param {Object} [overrides] */
function makeAction(overrides = {}) {
    return /** @type {any} */ ({
        id: 1,
        name: "Partners",
        type: "ir.actions.act_window",
        res_model: "partner",
        views: [
            [false, "list"],
            [false, "form"],
        ],
        ...overrides,
    });
}

describe.current.tags("desktop");

test("a refused leave aborts before anything is rendered", async () => {
    const am = makeFakeAm({ _confirmLeave: async () => false });
    expect(await executeActWindowAction(makeAction(), {}, am)).toBe(undefined);
    expect(am.__calls.updateUI).toEqual([]);
});

test("forceLeave is the only option forwarded to the leave check", async () => {
    const am = makeFakeAm();
    await executeActWindowAction(
        makeAction(),
        { forceLeave: true, viewType: "form", props: { x: 1 } },
        am,
    );
    expect(am.__calls.confirmLeave).toEqual([{ forceLeave: true }]);
});

test("a dialog action never asks permission to leave", async () => {
    const am = makeFakeAm();
    await executeActWindowAction(makeAction({ target: "new" }), {}, am);
    expect(am.__calls.confirmLeave).toEqual([]);
    expect(am.__calls.updateUI).toHaveLength(1);
});

test("opening in a new window never asks permission to leave", async () => {
    const am = makeFakeAm();
    await executeActWindowAction(makeAction(), { newWindow: true }, am);
    expect(am.__calls.confirmLeave).toEqual([]);
});

test("the requested viewType wins", async () => {
    const am = makeFakeAm();
    await executeActWindowAction(makeAction(), { viewType: "form" }, am);
    expect(am.__calls.updateUI[0].controller.view.type).toBe("form");
});

test("an unknown viewType falls back to the action's first view", async () => {
    const am = makeFakeAm();
    await executeActWindowAction(makeAction(), { viewType: "graph" }, am);
    expect(am.__calls.updateUI[0].controller.view.type).toBe("list");
});

test("on a small screen the mobile_view_mode replaces a same-arity view", async () => {
    const am = makeFakeAm({ env: { isSmall: true } });
    const action = makeAction({
        views: [
            [false, "list"],
            [false, "kanban"],
            [false, "form"],
        ],
        mobile_view_mode: "kanban",
    });
    await executeActWindowAction(action, {}, am);
    expect(am.__calls.updateUI[0].controller.view.type).toBe("kanban");
});

test("mobile_view_mode is ignored when arity does not match", async () => {
    const am = makeFakeAm({ env: { isSmall: true } });
    const action = makeAction({ mobile_view_mode: "form" });
    await executeActWindowAction(action, {}, am);
    expect(am.__calls.updateUI[0].controller.view.type).toBe("list");
});

test("the controller is cached on the action under its view type", async () => {
    const am = makeFakeAm();
    const action = makeAction();
    await executeActWindowAction(action, { viewType: "form" }, am);
    expect(action.controllers.form).toBe(am.__calls.updateUI[0].controller);
});

function proposedStack(am) {
    return am.__calls.updateUI.at(-1).options.newStack;
}

test("a lazy crumb is promoted when the action has a multi-record view", async () => {
    const am = makeFakeAm();
    const lazy = { lazy: true, props: {}, displayName: "stale" };
    const newStack = [{ jsId: "root" }, lazy];
    const action = makeAction({ display_name: "Partners (display)" });

    await executeActWindowAction(action, { newStack, viewType: "form" }, am);

    const proposed = proposedStack(am);
    expect(proposed).toHaveLength(2);
    const promoted = proposed[1];
    expect("lazy" in promoted).toBe(false);
    expect(promoted.displayName).toBe("Partners (display)");
    expect(promoted.action).toBe(action);
    expect(promoted.props.type).toBe("list");
});

test("promoting a lazy crumb leaves the caller's stack and controller untouched", async () => {
    const am = makeFakeAm();
    const lazy = { lazy: true, props: {}, displayName: "stale" };
    const newStack = [{ jsId: "root" }, lazy];

    await executeActWindowAction(makeAction(), { newStack, viewType: "form" }, am);

    expect(newStack).toHaveLength(2);
    expect(newStack[1]).toBe(lazy);
    expect(lazy.lazy).toBe(true);
    expect(lazy.displayName).toBe("stale");
    expect(lazy.props).toEqual({});
    expect(proposedStack(am)).not.toBe(newStack);
});

test("display_name wins over name when promoting a lazy crumb", async () => {
    const am = makeFakeAm();
    await executeActWindowAction(
        makeAction({ name: "Fallback", display_name: "Preferred" }),
        { newStack: [{ lazy: true, props: {} }], viewType: "form" },
        am,
    );
    expect(proposedStack(am).at(-1).displayName).toBe("Preferred");
});

test("a lazy crumb is dropped when the action has no multi-record view", async () => {
    const am = makeFakeAm();
    const lazy = { lazy: true, props: {} };
    const newStack = [{ jsId: "root" }, lazy];

    await executeActWindowAction(
        makeAction({ views: [[false, "form"]] }),
        { newStack, viewType: "form" },
        am,
    );

    expect(proposedStack(am)).toHaveLength(1);
    expect(proposedStack(am)[0].jsId).toBe("root");
    expect(newStack).toHaveLength(2);
});

test("a non-lazy tail is left alone", async () => {
    const am = makeFakeAm();
    const tail = { jsId: "tail", props: {} };
    const newStack = [tail];
    await executeActWindowAction(makeAction(), { newStack }, am);
    expect(newStack).toEqual([tail]);
});

test("an absent newStack is not a special case", async () => {
    const am = makeFakeAm();
    await executeActWindowAction(makeAction(), {}, am);
    expect(am.__calls.updateUI).toHaveLength(1);
});

test("an action whose only view is search is rejected", async () => {
    const am = makeFakeAm();
    await expect(
        executeActWindowAction(makeAction({ views: [[false, "search"]] }), {}, am),
    ).rejects.toThrow(/No view found/);
    expect(am.__calls.updateUI).toEqual([]);
});

test("an undefined view type is reported by name", async () => {
    const am = makeFakeAm();
    await expect(
        executeActWindowAction(
            makeAction({ views: [[false, "not_a_view_type"]] }),
            {},
            am,
        ),
    ).rejects.toThrow(/not_a_view_type/);
});
