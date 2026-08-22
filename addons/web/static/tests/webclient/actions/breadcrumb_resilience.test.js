// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    getService,
    makeMockEnv,
    makeMockServer,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { actionStorage } from "@web/webclient/actions/action_storage";

describe.current.tags("desktop");

const STACK = {
    action: 3,
    resId: 7,
    actionStack: [{ action: 1 }, { action: 2 }, { action: 3, resId: 7 }],
};

const NAMED_STACK = {
    action: 3,
    resId: 7,
    actionStack: [
        { action: 1, displayName: "First" },
        { action: 2, displayName: "Second" },
        { action: 3, resId: 7 },
    ],
};

async function restore(/** @type {any} */ state, /** @type {any} */ handler) {
    await makeMockServer();
    let calls = 0;
    onRpc("/web/action/load_breadcrumbs", async (request) => {
        calls++;
        return handler(await request.json());
    });
    patchWithCleanup(console, { warn: () => {} });
    await makeMockEnv();
    const am = /** @type {any} */ (getService("action"));
    const controllers = await am._controllersFromState(state);
    return { calls, names: controllers.map((/** @type {any} */ c) => c.displayName) };
}

const answerWithNames = (/** @type {{ params: any }} */ { params }) =>
    params.actions.map((/** @type {any} */ a) => ({
        display_name: `NAME-${a.action}`,
    }));

test("a healthy server names every crumb", async () => {
    const { calls, names } = await restore(STACK, answerWithNames);
    expect(calls).toBe(1);
    expect(names).toEqual(["NAME-1", "NAME-2"]);
});

test("a restore from an app-produced url survives the server being down", async () => {
    const { calls, names } = await restore(NAMED_STACK, () => {
        throw new Error("the server did not answer");
    });
    expect(calls).toBe(0);
    expect(names).toEqual(["First", "Second"]);
});

test("one named crumb lends its name to another for the same record", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", () => {
        throw new Error("should not fetch");
    });
    await makeMockEnv();
    const am = /** @type {any} */ (getService("action"));
    const controllers = await am._controllersFromState({
        action: 9,
        actionStack: [
            { action: 4, model: "partner", resId: 1, displayName: "The record" },
            { action: 4, model: "partner", resId: 1 },
            { action: 9 },
        ],
    });
    expect(controllers.map((/** @type {any} */ c) => c.displayName)).toEqual([
        "The record",
        "The record",
    ]);
});

test("a server that says the action is gone still drops the crumb", async () => {
    const { names } = await restore(
        STACK,
        (/** @type {{ params: any }} */ { params }) =>
            params.actions.map((/** @type {any} */ a) =>
                a.action === 1 ? {} : { display_name: "Kept" },
            ),
    );
    expect(names).toEqual(["Kept"]);
});

test("an unnameable leaf does not take its live ancestors with it", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", async (request) => {
        const { params } = await request.json();
        return params.actions.map((/** @type {any} */ a) =>
            a.action === 3 ? {} : { display_name: `N${a.action}` },
        );
    });
    patchWithCleanup(console, { warn: () => {} });
    await makeMockEnv();
    const am = /** @type {any} */ (getService("action"));

    /** @type {string[]} */
    let dispatchedStack = [];
    patchWithCleanup(am, {
        doAction(/** @type {any} */ actionRequest, /** @type {any} */ options) {
            dispatchedStack = options.newStack.map(
                (/** @type {any} */ c) => c.displayName,
            );
            return Promise.resolve();
        },
    });

    await am.loadState({
        model: "unknown.model",
        actionStack: [
            { action: 1 },
            { action: 2 },
            { action: 3 },
            { model: "unknown.model" },
        ],
    });

    expect(dispatchedStack).toEqual(["N1", "N2"]);
});

test("the cut still lands right when the stack came from actionStorage", async () => {
    await makeMockServer();
    onRpc("/web/action/load_breadcrumbs", async (request) => {
        const { params } = await request.json();
        return params.actions.map((/** @type {any} */ a) => ({
            display_name: `N${a.action}`,
        }));
    });
    patchWithCleanup(console, { warn: () => {} });
    await makeMockEnv();
    const am = /** @type {any} */ (getService("action"));

    const state = {
        model: "unknown.model",
        actionStack: [{ action: 1 }, { action: 2 }, { model: "unknown.model" }],
    };
    actionStorage.setCurrentState({ ...state, globalState: { searchModel: "x" } });

    /** @type {string[]} */
    let dispatchedStack = [];
    patchWithCleanup(am, {
        doAction(/** @type {any} */ actionRequest, /** @type {any} */ options) {
            dispatchedStack = options.newStack.map(
                (/** @type {any} */ c) => c.displayName,
            );
            return Promise.resolve();
        },
    });

    await am.loadState(state);

    expect(dispatchedStack).toEqual(["N1"]);
});

test("a name from the url is not remembered for later navigations", async () => {
    await makeMockServer();
    let calls = 0;
    onRpc("/web/action/load_breadcrumbs", async (request) => {
        calls++;
        const { params } = await request.json();
        return params.actions.map(() => ({ display_name: "Renamed on the server" }));
    });
    await makeMockEnv();
    const am = /** @type {any} */ (getService("action"));

    const first = await am._controllersFromState({
        action: 2,
        actionStack: [{ action: 1, displayName: "Stale from the url" }, { action: 2 }],
    });
    expect(first.map((/** @type {any} */ c) => c.displayName)).toEqual([
        "Stale from the url",
    ]);
    expect(calls).toBe(0);

    const second = await am._controllersFromState({
        action: 2,
        actionStack: [{ action: 1 }, { action: 2 }],
    });
    expect(second.map((/** @type {any} */ c) => c.displayName)).toEqual([
        "Renamed on the server",
    ]);
    expect(calls).toBe(1);
});
