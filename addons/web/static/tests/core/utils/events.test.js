// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { isEventHandled, markEventHandled } from "@web/core/utils/dom/events";

describe.current.tags("headless");

describe("markEventHandled / isEventHandled", () => {
    test("unmarked event is not handled", () => {
        const ev = new Event("click");
        expect(isEventHandled(ev, "some.handler")).toBe(false);
    });

    test("marked event is recognized as handled", () => {
        const ev = new Event("click");
        markEventHandled(ev, "some.handler");
        expect(isEventHandled(ev, "some.handler")).toBe(true);
    });

    test("different mark names are independent", () => {
        const ev = new Event("click");
        markEventHandled(ev, "handler_a");
        expect(isEventHandled(ev, "handler_a")).toBe(true);
        expect(isEventHandled(ev, "handler_b")).toBe(false);
    });

    test("multiple marks on same event", () => {
        const ev = new Event("click");
        markEventHandled(ev, "handler_a");
        markEventHandled(ev, "handler_b");
        expect(isEventHandled(ev, "handler_a")).toBe(true);
        expect(isEventHandled(ev, "handler_b")).toBe(true);
        expect(isEventHandled(ev, "handler_c")).toBe(false);
    });

    test("different events are independent", () => {
        const ev1 = new Event("click");
        const ev2 = new Event("click");
        markEventHandled(ev1, "handler");
        expect(isEventHandled(ev1, "handler")).toBe(true);
        expect(isEventHandled(ev2, "handler")).toBe(false);
    });
});
