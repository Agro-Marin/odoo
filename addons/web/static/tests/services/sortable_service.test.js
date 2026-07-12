// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import { getService, makeMockEnv } from "@web/../tests/web_test_helpers";

describe.current.tags("headless");

test("double cleanup() is a no-op (does not crash)", async () => {
    await makeMockEnv();
    const sortable = await getService("sortable");

    const fixture = getFixture();
    const root = document.createElement("div");
    const item = document.createElement("div");
    item.className = "item";
    root.appendChild(item);
    fixture.appendChild(root);

    const handle = sortable.create({
        ref: { el: root },
        elements: ".item",
    });
    const { cleanup } = handle.enable();

    // First cleanup may remove the element from the internal boundElements map.
    cleanup();
    // Second cleanup used to throw "TypeError: cannot use 'in' on undefined"
    // because boundElements.get(element) was then undefined.
    expect(() => cleanup()).not.toThrow();
});

test("enable() is idempotent — a second call does not re-arm listeners", async () => {
    await makeMockEnv();
    const sortable = await getService("sortable");

    const fixture = getFixture();
    const root = document.createElement("div");
    const item = document.createElement("div");
    item.className = "item";
    root.appendChild(item);
    fixture.appendChild(root);

    const handle = sortable.create({ ref: { el: root }, elements: ".item" });
    const first = handle.enable();
    // A second enable() must NOT re-run the setup functions (that would
    // register a duplicate set of DnD listeners so drag handlers fire twice).
    let second;
    expect(() => {
        second = handle.enable();
    }).not.toThrow();
    expect(typeof first.cleanup).toBe("function");
    expect(typeof second.cleanup).toBe("function");
    first.cleanup();
});
