// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    makeMockServer,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { actionStorage } from "@web/webclient/actions/action_storage";
import { BreadcrumbCache } from "@web/webclient/actions/breadcrumb_cache";
import {
    buildBreadcrumbs,
    controllersFromState,
    isMenuController,
    refreshBreadcrumbDisplayNames,
} from "@web/webclient/actions/breadcrumb_manager";

/**
 * @param {Object} [overrides]
 */
function makeFakeAm(overrides = {}) {
    const calls = { restore: [], stateToUrl: [] };
    const am = {
        router: {
            stateToUrl: (state) => {
                calls.stateToUrl.push(state);
                return `/odoo/url-for-${state?.action ?? "none"}`;
            },
        },
        restore: (jsId) => calls.restore.push(jsId),
        breadcrumbCache: new BreadcrumbCache(),
        _makeController: (params) => ({ ...params }),
        ...overrides,
    };
    am.__calls = calls;
    return am;
}

/** @param {Object} [overrides] */
function makeController(overrides = {}) {
    return {
        jsId: "controller_1",
        displayName: "First",
        action: { id: 1, type: "ir.actions.act_window" },
        props: { type: "list" },
        state: { action: 1, model: "partner", resId: false },
        ...overrides,
    };
}

describe.current.tags("desktop");

test("the home-menu pseudo-action is recognised by either spelling", async () => {
    expect(isMenuController({ tag: "menu" })).toBe(true);
    expect(isMenuController({ id: "menu" })).toBe(true);
    expect(isMenuController({ tag: "other", id: 3 })).toBe(false);
    expect(isMenuController(undefined)).toBe(false);
    expect(isMenuController({})).toBe(false);
});

test("one crumb per controller, in stack order", async () => {
    const am = makeFakeAm();
    const stack = [
        makeController({ jsId: "a", displayName: "A" }),
        makeController({ jsId: "b", displayName: "B" }),
    ];
    const crumbs = buildBreadcrumbs(stack, am);
    expect(crumbs.map((c) => c.jsId)).toEqual(["a", "b"]);
    expect(crumbs.map((c) => c.name)).toEqual(["A", "B"]);
});

test("the home-menu controller is never given a crumb", async () => {
    const am = makeFakeAm();
    const stack = [
        makeController({ jsId: "menu", action: { tag: "menu" } }),
        makeController({ jsId: "real" }),
    ];
    expect(buildBreadcrumbs(stack, am).map((c) => c.jsId)).toEqual(["real"]);
});

test("name is a plain slot, so the reactive array can be written through", async () => {
    const am = makeFakeAm();
    const controller = makeController({ displayName: "Original" });
    const [crumb] = buildBreadcrumbs([controller], am);

    controller.displayName = "Changed On The Controller";
    expect(crumb.name).toBe("Original");

    crumb.name = "Written Through";
    expect(crumb.name).toBe("Written Through");
});

test("isFormView IS a getter, so it tracks the controller's live view type", async () => {
    const am = makeFakeAm();
    const controller = makeController({ props: { type: "list" } });
    const [crumb] = buildBreadcrumbs([controller], am);
    expect(crumb.isFormView).toBe(false);
    controller.props.type = "form";
    expect(crumb.isFormView).toBe(true);
});

test("isFormView tolerates a controller with no props", async () => {
    const am = makeFakeAm();
    const [crumb] = buildBreadcrumbs([makeController({ props: undefined })], am);
    expect(crumb.isFormView).toBe(false);
});

test("url is resolved lazily, through the router, from the controller's state", async () => {
    const am = makeFakeAm();
    const controller = makeController({ state: { action: 42 } });
    const [crumb] = buildBreadcrumbs([controller], am);
    expect(am.__calls.stateToUrl).toEqual([]);
    expect(crumb.url).toBe("/odoo/url-for-42");
    expect(am.__calls.stateToUrl).toHaveLength(1);
});

test("selecting a crumb restores its own controller", async () => {
    const am = makeFakeAm();
    const crumbs = buildBreadcrumbs(
        [makeController({ jsId: "a" }), makeController({ jsId: "b" })],
        am,
    );
    crumbs[1].onSelected();
    expect(am.__calls.restore).toEqual(["b"]);
});

test("a warm cache refreshes names with no RPC at all", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", () => {
        throw new Error("should not fetch");
    });
    const cache = new BreadcrumbCache();
    const controller = makeController({ displayName: "stale" });
    const key = JSON.stringify({ action: 1, model: "partner", resId: false });
    cache.set(key, { display_name: "fresh" });

    await refreshBreadcrumbDisplayNames([controller], cache);

    expect(controller.displayName).toBe("fresh");
});

test("existing display names are NOT trusted as cache seeds", async () => {
    await makeMockServer();
    let fetched = 0;
    onRpc("/web/action/load_breadcrumbs", async () => {
        fetched++;
        return [{ display_name: "from server" }];
    });
    const cache = new BreadcrumbCache();
    const controller = makeController({ displayName: "stale but present" });

    await refreshBreadcrumbDisplayNames([controller], cache);

    expect(fetched).toBe(1);
    expect(controller.displayName).toBe("from server");
});

test("a failed refresh keeps the current name and drops no controller", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", async () =>
        Promise.reject(new Error("nope")),
    );
    const cache = new BreadcrumbCache();
    const controller = makeController({ displayName: "keep me" });

    await refreshBreadcrumbDisplayNames([controller], cache);

    expect(controller.displayName).toBe("keep me");
});

test("client actions and the home menu are skipped — their names are local", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", () => {
        throw new Error("should not fetch");
    });
    const cache = new BreadcrumbCache();
    const controllers = [
        makeController({
            displayName: "Client",
            action: { type: "ir.actions.client", tag: "some_tag" },
        }),
        makeController({ displayName: "Menu", action: { tag: "menu" } }),
        makeController({ displayName: "Stateless", state: undefined }),
    ];

    await refreshBreadcrumbDisplayNames(controllers, cache);

    expect(controllers.map((c) => c.displayName)).toEqual([
        "Client",
        "Menu",
        "Stateless",
    ]);
});

test("duplicate controllers are fetched once and both updated", async () => {
    await makeMockServer();
    let fetchedKeys = null;
    onRpc("/web/action/load_breadcrumbs", async (request) => {
        const { params } = await request.json();
        fetchedKeys = params.actions;
        return [{ display_name: "shared" }];
    });
    const cache = new BreadcrumbCache();
    const a = makeController({ jsId: "a", displayName: "old" });
    const b = makeController({ jsId: "b", displayName: "old" });

    await refreshBreadcrumbDisplayNames([a, b], cache);

    expect(fetchedKeys).toHaveLength(1);
    expect([a.displayName, b.displayName]).toEqual(["shared", "shared"]);
});

test("restoring a stack that repeats a record asks the server for it once", async () => {
    await makeMockServer();
    let fetchedKeys = null;
    onRpc("/web/action/load_breadcrumbs", async (request) => {
        const { params } = await request.json();
        fetchedKeys = params.actions;
        return params.actions.map(() => ({ display_name: "Rec" }));
    });
    const am = makeFakeAm();

    const controllers = await controllersFromState(
        {
            action: 4,
            actionStack: [
                { action: 4, model: "partner", resId: 1 },
                { action: 4, model: "partner", resId: 1 },
                { action: 4, model: "partner", resId: 2 },
            ],
        },
        am,
    );

    expect(fetchedKeys).toHaveLength(1);
    expect(controllers.map((c) => c.displayName)).toEqual(["Rec", "Rec"]);
});

test("a state with no actionStack yields no virtual controllers", async () => {
    const am = makeFakeAm();
    expect(await controllersFromState({}, am)).toEqual([]);
    expect(await controllersFromState({ actionStack: [] }, am)).toEqual([]);
});

test("a state matching the stored one by url is replaced by the stored copy", async () => {
    actionStorage.setCurrentState({
        action: 5,
        actionStack: [{ action: 4, displayName: "From Storage" }, { action: 5 }],
    });
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", () => {
        throw new Error("should not fetch — the stored copy has the name");
    });
    const am = makeFakeAm();

    const controllers = await controllersFromState(
        { action: 5, actionStack: [{ action: 4 }, { action: 5 }] },
        am,
    );

    expect(controllers).toHaveLength(1);
    expect(controllers[0].displayName).toBe("From Storage");
});

test("the last entry is left to doAction — only its ancestors become virtual", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", async () => [{ display_name: "Ancestor" }]);
    const am = makeFakeAm();
    const state = {
        action: 2,
        actionStack: [
            { action: 1, displayName: "Ancestor" },
            { action: 2, displayName: "Leaf" },
        ],
    };

    const controllers = await controllersFromState(state, am);

    expect(controllers).toHaveLength(1);
    expect(controllers[0].virtual).toBe(true);
    expect(controllers[0].action.id).toBe(1);
});

test("a resId in an ancestor makes it a form controller", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", async () => [{ display_name: "Rec" }]);
    const am = makeFakeAm();
    const state = {
        action: 2,
        actionStack: [{ action: 1, model: "partner", resId: 5 }, { action: 2 }],
    };

    const [controller] = await controllersFromState(state, am);

    expect(controller.action.type).toBe("ir.actions.act_window");
    expect(controller.props.resId).toBe(5);
    expect(controller.props.type).toBe("form");
    expect(controller.currentState.resId).toBe(5);
});

test("an active_id is carried into both the action context and currentState", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", async () => [{ display_name: "X" }]);
    const am = makeFakeAm();
    const state = {
        action: 2,
        actionStack: [{ action: 1, active_id: 9 }, { action: 2 }],
    };

    const [controller] = await controllersFromState(state, am);

    expect(controller.action.context).toEqual({ active_id: 9 });
    expect(controller.currentState.active_id).toBe(9);
});

test("an inaccessible ancestor is dropped from the reconstructed stack", async () => {
    patchWithCleanup(console, { warn: () => {} });
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", async () => [
        { display_name: "Visible" },
        { error: "no access" },
    ]);
    const am = makeFakeAm();
    const state = {
        action: 3,
        actionStack: [{ action: 1 }, { action: 2 }, { action: 3 }],
    };

    const controllers = await controllersFromState(state, am);

    expect(controllers).toHaveLength(1);
    expect(controllers[0].action.id).toBe(1);
});

test("a form leaf marks its parent lazy so the name fetch can be skipped", async () => {
    await makeMockServer();
    let fetched = 0;
    onRpc("/web/action/load_breadcrumbs", async () => {
        fetched++;
        return [{ display_name: "Grandparent" }];
    });
    const am = makeFakeAm();
    const state = {
        action: 2,
        resId: 5,
        actionStack: [{ action: 1 }, { action: 2 }, { action: 2, resId: 5 }],
    };

    const controllers = await controllersFromState(state, am);

    expect(controllers.at(-1).lazy).toBe(true);
    expect(fetched).toBe(1);
});
