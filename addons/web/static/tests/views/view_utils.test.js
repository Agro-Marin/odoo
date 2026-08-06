// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { computeAggregatedValue } from "@web/views/view_measurements";
import { computeArchiveEnabled, handleBeforeUnload } from "@web/views/view_utils";

describe.current.tags("headless");

describe("computeAggregatedValue", () => {
    test("sum", () => {
        expect(computeAggregatedValue([], "sum")).toBe(0);
        expect(computeAggregatedValue([7], "sum")).toBe(7);
        expect(computeAggregatedValue([7, 3], "sum")).toBe(10);
        expect(computeAggregatedValue([7.23, 3.1], "sum")).toBe(10.33);
        expect(computeAggregatedValue([10, 2, -3, 2, -5, 27, 2], "sum")).toBe(35);
    });

    test("min", () => {
        expect(computeAggregatedValue([], "min")).toBe(Infinity);
        expect(computeAggregatedValue([7], "min")).toBe(7);
        expect(computeAggregatedValue([7, 3], "min")).toBe(3);
        expect(computeAggregatedValue([7.23, 3.1], "min")).toBe(3.1);
        expect(computeAggregatedValue([10, 2, -3, 2, -5, 27, 2], "min")).toBe(-5);
    });

    test("max", () => {
        expect(computeAggregatedValue([], "max")).toBe(-Infinity);
        expect(computeAggregatedValue([7], "max")).toBe(7);
        expect(computeAggregatedValue([7, 3], "max")).toBe(7);
        expect(computeAggregatedValue([7.23, 3.1], "max")).toBe(7.23);
        expect(computeAggregatedValue([10, 2, -3, 2, -5, 27, 2], "max")).toBe(27);
    });

    test("avg", () => {
        expect(computeAggregatedValue([], "avg")).toBe(NaN);
        expect(computeAggregatedValue([7], "avg")).toBe(7);
        expect(computeAggregatedValue([7, 3], "avg")).toBe(5);
        expect(computeAggregatedValue([7.23, 3.1], "avg")).toBe(5.165);
        expect(computeAggregatedValue([10, 2, -3, 2, -5, 27, 2], "avg")).toBe(5);
    });

    test("count", () => {
        expect(computeAggregatedValue([], "count")).toBe(0);
        expect(computeAggregatedValue([7], "count")).toBe(1);
        expect(computeAggregatedValue([7, 3], "count")).toBe(2);
        expect(computeAggregatedValue([7.23, 3.1], "count")).toBe(2);
        expect(computeAggregatedValue([10, 2, -3, 2, -5, 27, 2], "count")).toBe(7);
    });

    test("count_distinct", () => {
        expect(computeAggregatedValue([], "count_distinct")).toBe(0);
        expect(computeAggregatedValue([7], "count_distinct")).toBe(1);
        expect(computeAggregatedValue([7, 3], "count_distinct")).toBe(2);
        expect(computeAggregatedValue([7.23, 3.1], "count_distinct")).toBe(2);
        expect(
            computeAggregatedValue([10, 2, -3, 2, -5, 27, 2], "count_distinct"),
        ).toBe(5);
    });

    test("invalid aggregator", () => {
        expect(() => computeAggregatedValue([])).toThrow(
            "Invalid aggregator 'undefined'",
        );
        expect(() => computeAggregatedValue([], "oups")).toThrow(
            "Invalid aggregator 'oups'",
        );
    });
});

describe("computeArchiveEnabled", () => {
    const fields = {
        active: { readonly: false },
        x_active: { readonly: true },
        name: { readonly: false },
    };

    test("presence and readonly both read from fields by default", () => {
        expect(computeArchiveEnabled(fields)).toBe(true);
        expect(computeArchiveEnabled({ active: { readonly: true } })).toBe(false);
        expect(computeArchiveEnabled({ x_active: { readonly: false } })).toBe(true);
        expect(computeArchiveEnabled({ name: { readonly: false } })).toBe(false);
    });

    test("presentIn scopes presence without changing where readonly is read", () => {
        expect(computeArchiveEnabled(fields, { presentIn: { active: {} } })).toBe(true);
        expect(computeArchiveEnabled(fields, { presentIn: { name: {} } })).toBe(false);
        expect(computeArchiveEnabled(fields, { presentIn: { x_active: {} } })).toBe(
            false,
        );
    });

    test("a field present only in presentIn does not throw", () => {
        expect(computeArchiveEnabled({}, { presentIn: { active: {} } })).toBe(false);
    });
});

describe("handleBeforeUnload", () => {
    const makeEvent = () => {
        const ev = {
            prevented: false,
            returnValue: "",
            preventDefault() {
                this.prevented = true;
            },
        };
        return /** @type {BeforeUnloadEvent & { prevented: boolean }} */ (
            /** @type {unknown} */ (ev)
        );
    };
    const record = /** @type {any} */ ({ resId: 1, dirty: true });

    test("beacon branch: successful urgent save does not prompt", async () => {
        const ev = makeEvent();
        await handleBeforeUnload(ev, {
            record,
            inDialog: false,
            useSendBeacon: true,
            urgentSave: () => Promise.resolve(true),
        });
        expect(ev.prevented).toBe(false);
    });

    test("beacon branch: unconfirmed urgent save prompts", async () => {
        const ev = makeEvent();
        await handleBeforeUnload(ev, {
            record,
            inDialog: false,
            useSendBeacon: true,
            urgentSave: () => Promise.resolve(false),
        });
        expect(ev.prevented).toBe(true);
        expect(ev.returnValue).toBe("Unsaved changes");
    });

    test("beacon branch: rejected urgent save prompts", async () => {
        const ev = makeEvent();
        await handleBeforeUnload(ev, {
            record,
            inDialog: false,
            useSendBeacon: true,
            urgentSave: () => Promise.reject(new Error("boom")),
        });
        expect(ev.prevented).toBe(true);
        expect(ev.returnValue).toBe("Unsaved changes");
    });
});
