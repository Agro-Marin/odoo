// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component, markup, xml } from "@odoo/owl";
import { makeMockServer, onRpc } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import {
    loadAction,
    makeController,
    preprocessAction,
    resolveClientAction,
} from "@web/webclient/actions/action_loader";

/**
 * Mount-free tests for ``action_loader.js``.
 *
 * The module normalises action descriptors before anything else in the service
 * sees them — which means a mistake here is visible everywhere and diagnosable
 * nowhere. It reaches exactly one manager member (``_nextId``), so the fake is
 * a one-liner.
 *
 * @param {Object} [overrides]
 */
function makeFakeAm(overrides = {}) {
    let id = 0;
    return { _nextId: () => ++id, ...overrides };
}

class SomeClientAction extends Component {
    static template = xml`<div/>`;
    static props = ["*"];
}

describe.current.tags("desktop");

test("a client action resolves by registry key", async () => {
    registry.category("actions").add("al_by_key", SomeClientAction);
    const [key, entry] = resolveClientAction("al_by_key");
    expect(key).toBe("al_by_key");
    expect(entry).toBe(SomeClientAction);
});

test("a client action resolves by its declared path", async () => {
    class PathedAction extends SomeClientAction {}
    /** @type {any} */ (PathedAction).path = "my-path";
    registry.category("actions").add("al_by_path", PathedAction);
    const [key, entry] = resolveClientAction("my-path");
    expect(key).toBe("al_by_path");
    expect(entry).toBe(PathedAction);
});

test("an unknown key destructures cleanly to a pair of undefineds", async () => {
    const [key, entry] = resolveClientAction("al_nothing_here");
    expect(key).toBe(undefined);
    expect(entry).toBe(undefined);
});

test("a numeric action id is normalised to a string key", async () => {
    registry.category("actions").add("42", SomeClientAction);
    const [key] = resolveClientAction(42);
    expect(key).toBe("42");
    expect(typeof key).toBe("string");
});

test("a registered tag becomes a client action without touching the server", async () => {
    await makeMockServer();
    onRpc("/web/action/load", () => {
        throw new Error("should not load");
    });
    registry.category("actions").add("al_tag", SomeClientAction);

    expect(await loadAction("al_tag")).toEqual({
        target: "current",
        tag: "al_tag",
        type: "ir.actions.client",
    });
});

test("an id is fetched and returned as a fresh object", async () => {
    await makeMockServer();
    const served = { id: 3, type: "ir.actions.act_window", res_model: "partner" };
    onRpc("/web/action/load", async () => served);

    const action = await loadAction(3);

    expect(action).toEqual(served);
    expect(action).not.toBe(served);
});

test("server-provided help is turned into markup", async () => {
    await makeMockServer();
    onRpc("/web/action/load", async () => ({
        id: 3,
        type: "ir.actions.act_window",
        help: "<p>Nothing yet</p>",
    }));
    const action = await loadAction(3);
    expect(action.help?.toString()).toBe("<p>Nothing yet</p>");
    expect(typeof action.help).not.toBe("string");
});

test("an action descriptor passed directly is returned untouched", async () => {
    const descriptor = { type: "ir.actions.act_window", res_model: "partner" };
    expect(await loadAction(descriptor)).toBe(descriptor);
});

test("the request context is merged over the user's, minus params", async () => {
    await makeMockServer();
    /** @type {any} */
    let sentContext = null;
    onRpc("/web/action/load", async (request) => {
        const { params } = await request.json();
        sentContext = params.context;
        return { id: 3, type: "ir.actions.act_window" };
    });

    await loadAction(3, { custom: 1, params: { should: "be dropped" } });

    expect(sentContext.custom).toBe(1);
    expect(sentContext.uid).toBe(user.context.uid);
    expect("params" in sentContext).toBe(false);
});

test("every controller gets a unique jsId and starts unmounted", async () => {
    const am = makeFakeAm();
    const a = makeController({ foo: 1 }, am);
    const b = makeController({ foo: 2 }, am);
    expect(a.jsId).toBe("controller_1");
    expect(b.jsId).toBe("controller_2");
    expect(a.isMounted).toBe(false);
    expect(a.foo).toBe(1);
});

test("preprocessing never mutates the action it was given", async () => {
    const am = makeFakeAm();
    const original = { type: "ir.actions.act_window", views: [[false, "list"]] };
    const snapshot = JSON.stringify(original);

    const processed = preprocessAction(original, {}, am);

    expect(JSON.stringify(original)).toBe(snapshot);
    expect(processed).not.toBe(original);
});

test("_originalAction is the pre-normalisation snapshot, and never nests", async () => {
    const am = makeFakeAm();
    const once = preprocessAction(
        { type: "ir.actions.act_window", views: [[false, "list"]], id: 5 },
        {},
        am,
    );
    expect(JSON.parse(/** @type {string} */ (once._originalAction)).id).toBe(5);
    const twice = preprocessAction(once, {}, am);
    expect(
        "_originalAction" in JSON.parse(/** @type {string} */ (twice._originalAction)),
    ).toBe(false);
});

test("a non-serializable action leaves _originalAction unset rather than throwing", async () => {
    const am = makeFakeAm();
    const cyclic = { type: "ir.actions.client" };
    /** @type {any} */ (cyclic).self = cyclic;
    const processed = preprocessAction(cyclic, {}, am);
    expect(processed._originalAction).toBe(undefined);
});

test("a string domain is evaluated, a list domain is left alone", async () => {
    const am = makeFakeAm();
    const evaluated = preprocessAction(
        { type: "ir.actions.act_window", views: [], domain: "[('id', '=', 1)]" },
        {},
        am,
    );
    expect(evaluated.domain).toEqual([["id", "=", 1]]);

    const literal = [["id", "=", 2]];
    const kept = preprocessAction(
        { type: "ir.actions.act_window", views: [], domain: literal },
        {},
        am,
    );
    expect(kept.domain).toBe(literal);
});

test("an absent domain becomes an empty list", async () => {
    const am = makeFakeAm();
    expect(
        preprocessAction({ type: "ir.actions.act_window", views: [] }, {}, am).domain,
    ).toEqual([]);
});

test("visually empty help is dropped, real help is kept", async () => {
    const am = makeFakeAm();
    const empty = preprocessAction(
        { type: "ir.actions.act_window", views: [], help: markup("<p><br></p>") },
        {},
        am,
    );
    expect("help" in empty).toBe(false);

    const real = preprocessAction(
        { type: "ir.actions.act_window", views: [], help: markup("<p>Try this</p>") },
        {},
        am,
    );
    expect(real.help?.toString()).toBe("<p>Try this</p>");
});

test("window and client actions default to target current; others do not", async () => {
    const am = makeFakeAm();
    const target = (action) => preprocessAction(action, {}, am).target;
    expect(target({ type: "ir.actions.act_window", views: [] })).toBe("current");
    expect(target({ type: "ir.actions.client" })).toBe("current");
    expect(target({ type: "ir.actions.act_window", views: [], target: "new" })).toBe(
        "new",
    );
    expect(target({ type: "ir.actions.report" })).toBe(undefined);
});

test("a search view is appended when the action has a real multi-record view", async () => {
    const am = makeFakeAm();
    const action = preprocessAction(
        {
            type: "ir.actions.act_window",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            search_view_id: [9, "a search view"],
        },
        {},
        am,
    );
    expect(action.views).toEqual([
        [false, "list"],
        [false, "form"],
        [9, "search"],
    ]);
});

test("a form-only action is reduced to the form view, with no search appended", async () => {
    const am = makeFakeAm();
    const action = preprocessAction(
        {
            type: "ir.actions.act_window",
            views: [
                [false, "form"],
                [false, "search"],
            ],
        },
        {},
        am,
    );
    expect(action.views).toEqual([[false, "form"]]);
});

test("the views array is copied, not shared with the source action", async () => {
    const am = makeFakeAm();
    const views = [[false, "list"]];
    const action = preprocessAction({ type: "ir.actions.act_window", views }, {}, am);
    expect(action.views).not.toBe(views);
    expect(views).toEqual([[false, "list"]]);
});

test("no_breadcrumbs is lifted out of the context onto the action", async () => {
    const am = makeFakeAm();
    const action = preprocessAction(
        {
            type: "ir.actions.act_window",
            views: [[false, "list"]],
            context: { no_breadcrumbs: true, keep: 1 },
        },
        {},
        am,
    );
    expect(action._noBreadcrumbs).toBe(true);
    expect("no_breadcrumbs" in (action.context ?? {})).toBe(false);
    expect(action.context?.keep).toBe(1);
});

test("every processed action gets a distinct jsId and a controllers map", async () => {
    const am = makeFakeAm();
    const a = preprocessAction({ type: "ir.actions.act_window", views: [] }, {}, am);
    const b = preprocessAction({ type: "ir.actions.act_window", views: [] }, {}, am);
    expect(a.jsId).toBe("action_1");
    expect(b.jsId).toBe("action_2");
    expect(a.controllers).toEqual({});
    expect(a.controllers).not.toBe(b.controllers);
});

test("the caller context is merged in, but the user context only EVALUATES it", async () => {
    const am = makeFakeAm();
    const action = preprocessAction(
        { type: "ir.actions.act_window", views: [], context: { fromAction: 1 } },
        { fromCaller: 2 },
        am,
    );
    expect(action.context?.fromAction).toBe(1);
    expect(action.context?.fromCaller).toBe(2);
    expect("uid" in (action.context ?? {})).toBe(false);
});

test("a context expression is evaluated against the user context", async () => {
    const am = makeFakeAm();
    const action = preprocessAction(
        /** @type {any} */ ({
            type: "ir.actions.act_window",
            views: [],
            context: "{'owner': uid}",
        }),
        {},
        am,
    );
    expect(action.context?.owner).toBe(user.context.uid);
    expect("uid" in (action.context ?? {})).toBe(false);
});
