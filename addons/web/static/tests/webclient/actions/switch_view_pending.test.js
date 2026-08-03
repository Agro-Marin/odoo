// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { ActionManager } from "@web/webclient/actions/action_service";

/**
 * Where an incoming controller is spliced, and when a view switch is refused.
 *
 * ``_updateUI`` splices into ``_effectiveStack`` — the stack a pending dispatch
 * will land on — while ``switchView`` and ``_getView`` read ``controllerStack``,
 * the one still on screen. Two problems followed from that, fixed separately:
 *
 *  - a position measured on one stack was applied to the other. Every branch of
 *    ``_computeStackIndex`` now resolves against the stack it splices, so there
 *    is no number to carry across;
 *  - even resolved correctly, switching a view of the outgoing action onto the
 *    incoming stack has nothing to mean. It is declined, as it is behind a
 *    dialog.
 */
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

    // list -> form pushes: the mono-record view stacks onto the multi-record
    // one it was opened from.
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

    // A dispatch is in flight that will land on a stack of its own — a
    // browser Back, or any loadState — and has not committed yet.
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
