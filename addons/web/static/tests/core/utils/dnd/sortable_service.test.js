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

    cleanup();
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
    /** @type {any} */
    let second;
    expect(() => {
        second = handle.enable();
    }).not.toThrow();
    expect(typeof first.cleanup).toBe("function");
    expect(typeof second.cleanup).toBe("function");
    first.cleanup();
});

test("cleanup() disarms the element: a later pointerdown starts nothing", async () => {
    const { pointerDown, pointerUp } = await import("@odoo/hoot-dom");
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
        onWillStartDrag: () => expect.step("will-start"),
    });
    const { cleanup } = handle.enable();
    await pointerDown(item);
    await pointerUp(item);
    expect.verifySteps(["will-start"]);

    cleanup();
    await pointerDown(item);
    await pointerUp(item);
    expect.verifySteps([]);
});
