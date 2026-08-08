// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { findView, getActionMode } from "@web/webclient/actions/action_views";

/**
 * UNIT COVERAGE for the two view/target resolvers the dispatch path runs on
 * every action.
 *
 * `getActionMode` decides what `ACTION_MANAGER:UI-UPDATED` reports, which is
 * what makes the web client go fullscreen (`WebClient` listens for it and
 * hides the navbar). Its PRECEDENCE is the whole of it and was stated nowhere:
 * a dialog wins over everything, a client action's registry target wins over
 * the action's own `fullscreen`, and `fullscreen` wins over the default.
 *
 * `findView` answers the mobile-view lookup in `act_window`, where "no such
 * view" and "no view type asked for" have to be the same answer or the caller
 * loses its fallback.
 */

describe.current.tags("desktop");

/**
 * Minimal stand-in for the `actions` registry category.
 *
 * @returns {any} Only `get` is implemented, so it is not a real Registry.
 */
function makeRegistry(entries = {}) {
    return {
        get(/** @type {string} */ key) {
            if (!(key in /** @type {Record<string, any>} */ (entries))) {
                throw new Error(`no client action "${key}"`);
            }
            return /** @type {Record<string, any>} */ (entries)[key];
        },
    };
}

test("a dialog is 'new' whatever else the action says", () => {
    const registry = makeRegistry({ tagged: { target: "fullscreen" } });
    expect(getActionMode(/** @type {any} */ ({ target: "new" }), registry)).toBe("new");
    // Even when the registry entry would force another target.
    expect(
        getActionMode(
            { target: "new", type: "ir.actions.client", tag: "tagged" },
            registry,
        ),
    ).toBe("new");
});

test("a client action's registry target overrides the action's own", () => {
    // This is the precedence that is easy to get backwards: the entry wins over
    // `fullscreen`, so a client action registered as `current` stays inside the
    // shell even when the record asks for fullscreen.
    const registry = makeRegistry({ pinned: { target: "current" } });
    expect(
        getActionMode(
            { target: "fullscreen", type: "ir.actions.client", tag: "pinned" },
            registry,
        ),
    ).toBe("current");
});

test("a client action with no registry target falls through to the action's", () => {
    const registry = makeRegistry({ plain: {} });
    const action = { type: "ir.actions.client", tag: "plain" };
    expect(getActionMode({ ...action, target: "fullscreen" }, registry)).toBe(
        "fullscreen",
    );
    expect(getActionMode({ ...action, target: "current" }, registry)).toBe("current");
    expect(getActionMode(action, registry)).toBe("current");
});

test("a window action never consults the registry", () => {
    // `getActionMode` runs on every commit, including for act_window actions
    // that carry a `tag`-like key by accident; touching the registry for those
    // would throw on a key that was never registered.
    const registry = makeRegistry();
    expect(
        getActionMode(
            {
                type: "ir.actions.act_window",
                target: "fullscreen",
                tag: "unregistered",
            },
            registry,
        ),
    ).toBe("fullscreen");
    expect(getActionMode({ type: "ir.actions.act_window" }, registry)).toBe("current");
});

test("an unknown target degrades to current rather than passing through", () => {
    const registry = makeRegistry();
    expect(getActionMode(/** @type {any} */ ({ target: "main" }), registry)).toBe(
        "current",
    );
    expect(getActionMode(/** @type {any} */ ({ target: "self" }), registry)).toBe(
        "current",
    );
    expect(getActionMode(/** @type {any} */ ({}), registry)).toBe("current");
});

const VIEWS = [
    { type: "list", multiRecord: true },
    { type: "kanban", multiRecord: true },
    { type: "form", multiRecord: false },
];

test("findView matches on type AND multiRecord together", () => {
    expect(findView(VIEWS, true, "kanban")).toBe(VIEWS[1]);
    expect(findView(VIEWS, false, "form")).toBe(VIEWS[2]);
    // Right type, wrong arity: not a match, or `act_window` would swap a
    // multi-record view in for a single-record one on mobile.
    expect(findView(VIEWS, false, "kanban")).toBe(undefined);
    expect(findView(VIEWS, true, "form")).toBe(undefined);
});

test("no view type asked for is the same answer as no such view", () => {
    // `act_window` calls this with `action.mobile_view_mode`, which is usually
    // unset, and relies on `|| view` to keep the view it already chose. Any
    // answer other than a falsy one there would silently override it.
    expect(findView(VIEWS, true, undefined)).toBe(undefined);
    expect(findView(VIEWS, true, "gantt")).toBe(undefined);
    expect(findView([], true, "list")).toBe(undefined);
});
