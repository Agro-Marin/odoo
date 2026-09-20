// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { markup } from "@odoo/owl";
import { DateTime } from "@web/core/l10n/luxon";
import {
    extractInfoFromGroupData,
    sameFieldValue,
} from "@web/model/relational_model/field_values";

describe.current.tags("headless");

const selectionField = {
    name: "state",
    type: "selection",
    selection: [
        ["draft", "Draft"],
        ["done", "Done"],
    ],
};

function makeGroupInfo(field, rawValue) {
    return extractInfoFromGroupData(
        { __count: 1, __extra_domain: [], [field.name]: rawValue },
        [field.name],
        { [field.name]: field },
        [],
    );
}

test("selection group with a valid value uses the selection label", () => {
    const info = makeGroupInfo(selectionField, "done");
    expect(info.displayName).toBe("Done");
});

test("selection group with a falsy value falls back to 'None'", () => {
    const info = makeGroupInfo(selectionField, false);
    expect(info.displayName).toBe("None");
});

test("selection group with a falsy value honors falsy_value_label", () => {
    const info = makeGroupInfo(
        { ...selectionField, falsy_value_label: "Not set" },
        false,
    );
    expect(info.displayName).toBe("Not set");
});

describe("sameFieldValue", () => {
    test("reads each type the way a reload compares it", () => {
        const same = (
            /** @type {string} */ type,
            /** @type {any} */ a,
            /** @type {any} */ b,
        ) => sameFieldValue(/** @type {any} */ ({ type }), a, b);
        expect(same("char", "a", "a")).toBe(true);
        expect(same("char", "a", "b")).toBe(false);
        expect(
            same(
                "many2one",
                { id: 1, display_name: "x" },
                { id: 1, display_name: "x" },
            ),
        ).toBe(true);
        expect(
            same(
                "many2one",
                { id: 1, display_name: "x" },
                { id: 1, display_name: "y" },
            ),
        ).toBe(false);
        expect(same("many2one", false, false)).toBe(true);
        expect(
            same(
                "date",
                DateTime.fromISO("2024-01-05"),
                DateTime.fromISO("2024-01-05"),
            ),
        ).toBe(true);
        expect(
            same(
                "date",
                DateTime.fromISO("2024-01-05"),
                DateTime.fromISO("2024-01-06"),
            ),
        ).toBe(false);
        expect(same("date", "2024-01-05", "2024-01-05")).toBe(true);
        expect(same("date", false, DateTime.fromISO("2024-01-05"))).toBe(false);
        expect(same("html", markup("<b>x</b>"), markup("<b>x</b>"))).toBe(true);
        expect(same("json", { a: [1, 2] }, { a: [1, 2] })).toBe(true);
        expect(same("json", { a: [1, 2] }, { a: [1, 3] })).toBe(false);
        expect(
            same(
                "reference",
                { resModel: "m", resId: 1, displayName: "x" },
                { resModel: "m", resId: 1, displayName: "x" },
            ),
        ).toBe(true);
        const list = {};
        expect(same("one2many", list, list)).toBe(true);
        expect(same("one2many", list, {})).toBe(false);
    });
});
