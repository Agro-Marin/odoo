import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

const seen = { win: 0, doc: 0, body: 0 };

test("a test's window, document and body listeners are registered", () => {
    window.addEventListener("test-isolation-probe", () => seen.win++);
    document.addEventListener("test-isolation-probe", () => seen.doc++);
    document.body.addEventListener("test-isolation-probe", () => seen.body++);
    window.dispatchEvent(new Event("test-isolation-probe"));
    document.dispatchEvent(new Event("test-isolation-probe"));
    document.body.dispatchEvent(new Event("test-isolation-probe"));
    expect(seen).toEqual({ win: 1, doc: 1, body: 1 });
});

test("none of them survives into the next test", () => {
    window.dispatchEvent(new Event("test-isolation-probe"));
    document.dispatchEvent(new Event("test-isolation-probe"));
    document.body.dispatchEvent(new Event("test-isolation-probe"));
    expect(seen).toEqual({ win: 1, doc: 1, body: 1 });
});
