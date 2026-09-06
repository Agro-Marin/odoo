// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { useListOptionalFields } from "@web/views/list/list_optional_fields";

describe.current.tags("headless");

function makeStorage() {
    /** @type {Record<string, string>} */
    const store = {};
    return {
        store,
        getItem: (/** @type {string} */ k) => (k in store ? store[k] : null),
        setItem: (/** @type {string} */ k, /** @type {string} */ v) => {
            store[k] = String(v);
        },
    };
}

const COLUMNS = [
    { type: "field", name: "a", optional: "show" },
    { type: "field", name: "b", optional: "hide" },
    { type: "field", name: "c" },
    {
        type: "field",
        name: "p1",
        optional: "hide",
        relatedPropertyField: { id: "grp" },
    },
    {
        type: "field",
        name: "p2",
        optional: "hide",
        relatedPropertyField: { id: "grp" },
    },
    { type: "widget", name: "w", optional: "show" },
];

function setup(/** @type {ReturnType<typeof makeStorage>} */ storage) {
    patchWithCleanup(browser, { localStorage: storage });
    /** @type {Record<string, boolean>} */
    const active = {};
    let saved = 0;
    const opt = useListOptionalFields("optional_fields,k", "debug_open_view,k", {
        getAllColumns: () => COLUMNS,
        getOptionalActiveFields: () => active,
        onSave: () => saved++,
    });
    return { opt, active, savedCount: () => saved };
}

test("the arch's show/hide is the default; a stored list overrides it", () => {
    const storage = makeStorage();
    const { opt } = setup(storage);
    expect(opt.computeOptionalActiveFields()).toEqual({
        a: true,
        b: false,
        p1: false,
        p2: false,
    });
    storage.setItem("optional_fields,k", "b,p2");
    expect(opt.computeOptionalActiveFields()).toEqual({
        a: false,
        b: true,
        p1: false,
        p2: true,
    });
    expect(opt.debugOpenView).toBe(false);
});

test("toggling a field or a property group saves and re-renders", () => {
    const storage = makeStorage();
    const { opt, active, savedCount } = setup(storage);
    Object.assign(active, opt.computeOptionalActiveFields());
    let renders = 0;
    const render = () => renders++;
    opt.toggleOptionalField("b", render);
    expect(active.b).toBe(true);
    opt.saveOptionalActiveFields();
    expect(storage.store["optional_fields,k"]).toBe("a,b");
    opt.toggleOptionalFieldGroup("grp", render);
    expect(active.p1).toBe(true);
    expect(active.p2).toBe(true);
    opt.toggleOptionalFieldGroup("grp", render);
    expect(active.p1).toBe(false);
    expect(active.p2).toBe(false);
    expect(savedCount()).toBe(3);
    expect(renders).toBe(3);
    opt.toggleDebugOpenView(render);
    expect(opt.debugOpenView).toBe(true);
    expect(storage.store["debug_open_view,k"]).toBe("true");
});
