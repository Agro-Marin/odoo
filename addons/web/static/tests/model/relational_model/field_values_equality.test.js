// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { sameMany2OneValue } from "@web/model/relational_model/field_values";

describe.current.tags("headless");

test("many2one equality treats empty values consistently", () => {
    const emptyValues = /** @type {const} */ ([false, null, undefined]);
    for (const left of emptyValues) {
        for (const right of emptyValues) {
            expect(sameMany2OneValue(left, right)).toBe(true);
        }
        const record = { id: 1, display_name: "First" };
        expect(sameMany2OneValue(left, record)).toBe(false);
        expect(sameMany2OneValue(record, left)).toBe(false);
    }
});

test("many2one equality compares both the id and the display name", () => {
    expect(sameMany2OneValue({ id: 1 }, { id: 1 })).toBe(true);
    expect(sameMany2OneValue({ id: 1 }, { id: 2 })).toBe(false);
    expect(sameMany2OneValue({ id: 1 }, { id: 1, display_name: "First" })).toBe(false);
    expect(
        sameMany2OneValue(
            { id: 1, display_name: "First" },
            { id: 1, display_name: "First" },
        ),
    ).toBe(true);
    expect(
        sameMany2OneValue(
            { id: 1, display_name: "First" },
            { id: 1, display_name: "Renamed" },
        ),
    ).toBe(false);
});
