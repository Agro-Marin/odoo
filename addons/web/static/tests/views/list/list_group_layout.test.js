// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    countRecordsInGroup,
    getAggregateColumns,
    getGroupNameCellColSpan,
    getGroupPagerCellColspan,
} from "@web/views/list/list_group_layout";

describe.current.tags("headless");

const FIELDS = {
    name: { type: "char" },
    product: { type: "char" },
    qty: { type: "integer" },
    price: { type: "float" },
    seq: { type: "integer" },
};

/**
 * @param {string} name
 * @param {Record<string, any>} [extra]
 */
function col(name, extra = {}) {
    return { id: `col_${name}`, name, type: "field", ...extra };
}

const COLUMNS = [col("name"), col("product"), col("qty"), col("price")];

describe("getGroupNameCellColSpan", () => {
    test("spans up to the first aggregate column", () => {
        expect(getGroupNameCellColSpan(COLUMNS, FIELDS, { qty: 1 }, {})).toBe(2);
    });

    test("spans every column when nothing is aggregated", () => {
        expect(getGroupNameCellColSpan(COLUMNS, FIELDS, {}, {})).toBe(4);
    });

    test("the selector column adds one", () => {
        expect(
            getGroupNameCellColSpan(
                COLUMNS,
                FIELDS,
                { qty: 1 },
                { hasSelectors: true },
            ),
        ).toBe(3);
    });

    test("a handle column never counts as the first aggregate", () => {
        const columns = [col("seq", { widget: "handle" }), ...COLUMNS];
        expect(getGroupNameCellColSpan(columns, FIELDS, { seq: 1, qty: 1 }, {})).toBe(
            3,
        );
    });

    test("a non-aggregatable field type is not an aggregate", () => {
        expect(getGroupNameCellColSpan(COLUMNS, FIELDS, { name: "x" }, {})).toBe(4);
    });

    test("dropping one column before the first aggregate moves the boundary", () => {
        const narrowed = COLUMNS.filter((c) => c.name !== "product");
        expect(getGroupNameCellColSpan(COLUMNS, FIELDS, { qty: 1 }, {})).toBe(2);
        expect(getGroupNameCellColSpan(narrowed, FIELDS, { qty: 1 }, {})).toBe(1);
    });
});

describe("getAggregateColumns", () => {
    test("slices from the first to the last aggregate, inclusive", () => {
        const slice = getAggregateColumns(COLUMNS, FIELDS, { qty: 1, price: 2 });
        expect(slice.map((c) => c.name)).toEqual(["qty", "price"]);
    });

    test("includes non-aggregate columns sitting between two aggregates", () => {
        const columns = [col("qty"), col("name"), col("price")];
        const slice = getAggregateColumns(columns, FIELDS, { qty: 1, price: 2 });
        expect(slice.map((c) => c.name)).toEqual(["qty", "name", "price"]);
    });

    test("is empty when nothing is aggregated", () => {
        expect(getAggregateColumns(COLUMNS, FIELDS, {})).toEqual([]);
    });
});

describe("getGroupPagerCellColspan", () => {
    test("covers the columns after the last aggregate", () => {
        expect(getGroupPagerCellColspan(COLUMNS, FIELDS, { qty: 1 })).toBe(1);
    });

    test("is zero when nothing is aggregated", () => {
        expect(getGroupPagerCellColspan(COLUMNS, FIELDS, {})).toBe(0);
    });

    test("the open-form-view column adds one", () => {
        expect(
            getGroupPagerCellColspan(
                COLUMNS,
                FIELDS,
                { qty: 1 },
                { hasOpenFormViewColumn: true },
            ),
        ).toBe(2);
    });
});

describe("countRecordsInGroup", () => {
    const leaf = (n) => ({
        isFolded: false,
        list: { isGrouped: false, records: new Array(n).fill(0) },
    });

    test("counts a flat group's loaded records", () => {
        expect(countRecordsInGroup(leaf(3))).toBe(3);
    });

    test("a folded group counts as empty", () => {
        expect(countRecordsInGroup({ ...leaf(3), isFolded: true })).toBe(0);
    });

    test("recurses into nested groups", () => {
        const group = {
            isFolded: false,
            list: { isGrouped: true, groups: [leaf(2), leaf(5)] },
        };
        expect(countRecordsInGroup(group)).toBe(7);
    });

    test("a folded nested group contributes nothing", () => {
        const group = {
            isFolded: false,
            list: {
                isGrouped: true,
                groups: [leaf(2), { ...leaf(5), isFolded: true }],
            },
        };
        expect(countRecordsInGroup(group)).toBe(2);
    });
});
