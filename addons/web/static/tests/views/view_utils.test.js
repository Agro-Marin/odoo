// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { computeAggregatedValue } from "@web/views/view_measurements";
import {
    archiveConfirmationProps,
    buildOpenActionParams,
    buildStaticActionMenuItems,
    computeArchiveEnabled,
    handleBeforeUnload,
} from "@web/views/view_utils";

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

describe("buildStaticActionMenuItems", () => {
    test("composes the shared presentation with the caller's behaviour", () => {
        const items = buildStaticActionMenuItems({
            archive: { isAvailable: () => true, callback: () => "archived" },
            delete: { isAvailable: () => false, callback: () => "deleted" },
        });
        expect(items.archive.sequence).toBe(40);
        expect(items.archive.icon).toBe("oi oi-archive");
        expect(items.archive.isAvailable()).toBe(true);
        expect(items.archive.callback()).toBe("archived");
        expect(items.delete.class).toBe("text-danger");
        expect(items.delete.sequence).toBe(50);
    });

    test("the caller may override presentation, and an unknown key throws", () => {
        expect(
            buildStaticActionMenuItems({ delete: { skipSave: true } }).delete.skipSave,
        ).toBe(true);
        expect(() => buildStaticActionMenuItems({ archiv: {} })).toThrow(
            /No static action menu descriptor for "archiv"/,
        );
    });
});

describe("archiveConfirmationProps", () => {
    test("is defaults, so an archiveDialogProps override extends rather than replaces", () => {
        let archived = 0;
        const defaults = archiveConfirmationProps(() => archived++);
        expect(defaults.confirmLabel.toString()).toBe("Archive");
        defaults.confirm();
        expect(archived).toBe(1);

        const merged = {
            ...archiveConfirmationProps(() => archived++),
            body: "custom",
        };
        expect(merged.body).toBe("custom");
        merged.confirm();
        expect(archived).toBe(2);
    });

    test("the multi variant asks about the selection, the single one about the record", () => {
        expect(archiveConfirmationProps(() => {}).body.toString()).toMatch(
            /this record/,
        );
        expect(
            archiveConfirmationProps(() => {}, { multi: true }).body.toString(),
        ).toMatch(/all the selected records/);
    });
});

describe("buildOpenActionParams", () => {
    test("builds the doActionButton payload both views used to build inline", () => {
        let loaded = 0;
        const record = {
            resModel: "foo",
            resId: 3,
            resIds: [3, 4],
            context: { a: 1 },
            model: { root: { load: async () => loaded++ } },
        };
        const params = buildOpenActionParams({ action: "act", type: "object" }, record);
        expect(params.name).toBe("act");
        expect(params.type).toBe("object");
        expect(params.resModel).toBe("foo");
        expect(params.resId).toBe(3);
        expect(params.resIds).toEqual([3, 4]);
        expect(params.context).toEqual({ a: 1 });
        params.onClose();
        expect(loaded).toBe(1);
    });
});
