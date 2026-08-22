// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { findView, getActionMode } from "@web/webclient/actions/action_views";

describe.current.tags("desktop");

/**
 * @returns {any}
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
    expect(
        getActionMode(
            { target: "new", type: "ir.actions.client", tag: "tagged" },
            registry,
        ),
    ).toBe("new");
});

test("a client action's registry target overrides the action's own", () => {
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
    expect(findView(VIEWS, false, "kanban")).toBe(undefined);
    expect(findView(VIEWS, true, "form")).toBe(undefined);
});

test("no view type asked for is the same answer as no such view", () => {
    expect(findView(VIEWS, true, undefined)).toBe(undefined);
    expect(findView(VIEWS, true, "gantt")).toBe(undefined);
    expect(findView([], true, "list")).toBe(undefined);
});
