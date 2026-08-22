// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { ActionManager } from "@web/webclient/actions/action_service";

describe.current.tags("desktop");

function makeController(
    /** @type {any} */ jsId,
    /** @type {any} */ actionJsId,
    /** @type {any} */ viewType,
    /** @type {any} */ multiRecord,
) {
    const view = { type: viewType, multiRecord };
    return {
        jsId,
        action: {
            jsId: actionJsId,
            id: 1,
            type: "ir.actions.act_window",
            controllers: {},
        },
        view,
        views: [
            { type: "list", multiRecord: true },
            { type: "form", multiRecord: false },
        ],
        props: { type: viewType },
        config: {},
        state: {},
        currentState: {},
        isMounted: true,
    };
}

function makeManager() {
    const am = new ActionManager(
        /** @type {any} */ ({
            bus: new EventBus(),
            services: { title: { setParts() {} }, dialog: { closeAll() {} } },
        }),
        /** @type {any} */ ({
            current: {},
            pushState() {},
            stateToUrl: () => "",
            hideKeyFromUrl() {},
        }),
    );
    am._confirmLeave = async () => true;
    am._getViewInfo = (view) => ({
        props: { type: view.type },
        config: {},
        currentState: {},
        displayName: view.type,
    });
    /** @type {any[]} */
    const dispatches = [];
    /** @type {any} */ (am).__dispatches = dispatches;
    am._dispatchInline = async (dispatch) => {
        dispatches.push(dispatch);
    };
    return am;
}

test("with no dispatch pending, a view switch replaces the current view", async () => {
    const am = makeManager();
    const visible = makeController("c1", "a1", "list", true);
    am.controllerStack = [visible];

    await am.switchView("form");

    const { nextStack } = /** @type {any} */ (am).__dispatches[0];
    expect(nextStack.map((/** @type {any} */ c) => c.props.type)).toEqual([
        "list",
        "form",
    ]);
});

test("switching back to the multi-record view replaces the action's segment", async () => {
    const am = makeManager();
    const list = makeController("c1", "a1", "list", true);
    const form = makeController("c2", "a1", "form", false);
    am.controllerStack = [list, form];

    await am.switchView("list");

    const { nextStack } = /** @type {any} */ (am).__dispatches[0];
    expect(nextStack.map((/** @type {any} */ c) => c.props.type)).toEqual(["list"]);
});

test("a view switch during a pending dispatch does not mix the two stacks", async () => {
    const am = makeManager();
    const older = makeController("c0", "a0", "list", true);
    const visible = makeController("c1", "a1", "list", true);
    am.controllerStack = [older, visible];

    const incoming = makeController("c2", "a2", "list", true);
    const pendingBase = [incoming];
    am._pendingDispatch = /** @type {any} */ ({ baseStack: pendingBase });

    await am.switchView("form");

    expect(/** @type {any} */ (am).__dispatches).toEqual([], {
        message: "no view of the visible action is stacked onto the incoming one",
    });
    expect(am.controllerStack).toEqual([older, visible], {
        message: "nothing on screen moved",
    });
});

test("spliceAt is resolved against the stack being spliced", () => {
    const am = makeManager();
    const onScreen = [makeController("c0", "a0", "list", true)];
    const target = makeController("c9", "a9", "list", true);
    const elsewhere = [
        makeController("c1", "a1", "list", true),
        makeController("c2", "a2", "list", true),
        target,
    ];
    am.controllerStack = onScreen;

    const spliceAt = (/** @type {any} */ stack) =>
        stack.findIndex((/** @type {any} */ ct) => ct.jsId === target.jsId);
    expect(am._computeStackIndex({ spliceAt }, elsewhere)).toBe(2, {
        message: "the position is the one it holds in the stack handed over",
    });
    expect(am._computeStackIndex({ spliceAt }, onScreen)).toBe(-1);
});

test("a pending dispatch is still the pending one after a view switch", async () => {
    const am = makeManager();
    const visible = makeController("c1", "a1", "list", true);
    am.controllerStack = [visible];
    const pending = /** @type {any} */ ({
        baseStack: [makeController("c2", "a2", "list", true)],
    });
    am._pendingDispatch = pending;

    await am.switchView("form");

    expect(am._pendingDispatch).toBe(pending, {
        message: "the in-flight dispatch owns the slot until it settles",
    });
});

test("a spliceAt that misses appends instead of eating the last crumb", async () => {
    const am = makeManager();
    const a = makeController("c0", "a0", "list", true);
    const b = makeController("c1", "a1", "list", true);
    am.controllerStack = [a, b];
    const incoming = makeController("c2", "a2", "list", true);

    await am._updateUI(/** @type {any} */ (incoming), { spliceAt: () => -1 });

    const dispatched = /** @type {any} */ (am).__dispatches.at(-1);
    expect(dispatched.nextStack.map((/** @type {any} */ c) => c.jsId)).toEqual([
        "c0",
        "c1",
        "c2",
    ]);
});
