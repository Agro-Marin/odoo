// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchDate, patchTimeZone, triggerEvent } from "@web/../tests/helpers/utils";

describe.current.tags("headless");

test("patchDate preserves native construction and callable Date semantics", () => {
    patchTimeZone(0);
    const NativeDate = Date;
    const constructor = NativeDate.prototype.constructor;
    patchDate(2020, 0, 2, 3, 4, 5);
    const expected = NativeDate.UTC(2020, 0, 2, 3, 4, 5);
    expect(Date.now()).toBeGreaterThanOrEqual(expected);
    expect(Math.abs(Date.now() - expected)).toBeLessThan(1000);
    expect(typeof Date()).toBe("string");
    expect(new Date().getTime()).toBeGreaterThanOrEqual(expected);
    expect(new Date(123).getTime()).toBe(123);
    expect(new Date("2024-01-01T00:00:00Z").getUTCFullYear()).toBe(2024);
    expect(NativeDate.prototype.constructor).toBe(constructor);
    class DerivedDate extends Date {}
    expect(new DerivedDate()).toBeInstanceOf(DerivedDate);
    expect(new DerivedDate()).toBeInstanceOf(NativeDate);
});

test("triggerEvent retains pointer coordinates and accepts document targets", () => {
    const event = triggerEvent(
        document,
        null,
        "pointerdown",
        {
            pageX: 12,
            pageY: 34,
            pointerType: "pen",
        },
        { sync: true, skipVisibilityCheck: true },
    );
    expect(event).toBeInstanceOf(PointerEvent);
    if (!(event instanceof PointerEvent)) {
        throw new Error("Expected a pointer event");
    }
    expect(event.clientX).toBe(12);
    expect(event.clientY).toBe(34);
    expect(event.pointerType).toBe("pen");
    expect(event.bubbles).toBe(true);
});
