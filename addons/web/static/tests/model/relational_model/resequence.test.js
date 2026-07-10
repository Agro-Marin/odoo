// @ts-check

/**
 * Pure unit tests for resequence(): mock ORM, no OWL/DOM/server. Verifies
 * in-place reordering, the webResequence payload, and rollback on error.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    computeResequencePlan,
    resequence,
} from "@web/model/relational_model/resequence";

// Helpers

/**
 * Create a simple mock ORM that records the last webResequence call.
 * @param {{ reject?: boolean }} [opts]
 */
function makeMockOrm({ reject = false } = {}) {
    const calls = [];
    return {
        calls,
        webResequence: async (model, resIds, params) => {
            if (reject) {
                throw new Error("Server error");
            }
            calls.push({ model, resIds, params });
            // Return sequence values as if server assigned them
            return resIds.map((id, i) => ({
                id,
                [params.field_name]: params.offset + i,
            }));
        },
    };
}

/** Create an array of records with a sequence field. */
function makeRecords(specs) {
    return specs.map(([id, sequence]) => ({ id, sequence }));
}

// Basic resequence — move forward

describe("resequence — move forward", () => {
    test("moves a record from index 0 to index 2", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([
            [1, 10],
            [2, 20],
            [3, 30],
        ]);

        await resequence({
            records,
            resModel: "product.product",
            orm,
            fieldName: "sequence",
            movedId: 1,
            targetId: 3, // move after record 3
        });

        expect(records[2].id).toBe(1);
        expect(orm.calls.length).toBe(1);
        expect(orm.calls[0].model).toBe("product.product");
    });

    test("moves a record from index 2 to index 0", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([
            [1, 10],
            [2, 20],
            [3, 30],
        ]);

        await resequence({
            records,
            resModel: "res.partner",
            orm,
            fieldName: "sequence",
            movedId: 3,
            targetId: null, // move to first position
        });

        expect(records[0].id).toBe(3);
    });
});

// ORM call parameters

describe("resequence — ORM call parameters", () => {
    test("passes fieldName as field_name param", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([
            [1, 10],
            [2, 20],
        ]);

        await resequence({
            records,
            resModel: "sale.order",
            orm,
            fieldName: "priority",
            movedId: 2,
            targetId: null,
        });

        expect(orm.calls[0].params.field_name).toBe("priority");
    });

    test("offset is the minimum sequence of affected records", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([
            [1, 5],
            [2, 10],
            [3, 15],
        ]);

        // Move record 3 before record 1 (targetId = null)
        await resequence({
            records,
            resModel: "product.product",
            orm,
            fieldName: "sequence",
            movedId: 3,
            targetId: null,
        });

        // Moving to position 0 reorders all 3 records; offset = min sequence = 5.
        expect(orm.calls[0].params.offset).toBe(5);
    });

    test("passes context to ORM when provided", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([
            [1, 1],
            [2, 2],
        ]);
        const context = { company_id: 1 };

        await resequence({
            records,
            resModel: "res.partner",
            orm,
            fieldName: "sequence",
            movedId: 2,
            targetId: null,
            context,
        });

        expect(orm.calls[0].params.context).toBe(context);
    });
});

// Custom getSequence / getResId callbacks

describe("resequence — custom callbacks", () => {
    test("uses custom getSequence to read sequence", async () => {
        const orm = makeMockOrm();
        // Records where sequence is nested under .data
        const records = [
            { id: 1, data: { order: 10 } },
            { id: 2, data: { order: 20 } },
        ];

        await resequence({
            records,
            resModel: "x",
            orm,
            fieldName: "order",
            movedId: 2,
            targetId: null,
            getSequence: (r) => r.data.order,
        });

        expect(records[0].id).toBe(2);
        expect(orm.calls.length).toBe(1);
    });

    test("uses custom getResId to extract id", async () => {
        const orm = makeMockOrm();
        // Records with res_id instead of id
        const records = [
            { id: 1, res_id: 100, sequence: 1 },
            { id: 2, res_id: 200, sequence: 2 },
        ];

        await resequence({
            records,
            resModel: "x",
            orm,
            fieldName: "sequence",
            movedId: 2,
            targetId: null,
            getResId: (r) => r.res_id,
        });

        // resIds passed to ORM should use res_id values
        expect(orm.calls[0].resIds).toInclude(100);
    });
});

// Rollback on error

describe("resequence — rollback on ORM error", () => {
    test("restores original order when ORM throws", async () => {
        const orm = makeMockOrm({ reject: true });
        const records = makeRecords([
            [1, 10],
            [2, 20],
            [3, 30],
        ]);
        const originalOrder = records.map((r) => r.id);

        let thrown = false;
        try {
            await resequence({
                records,
                resModel: "x",
                orm,
                fieldName: "sequence",
                movedId: 1,
                targetId: 3,
            });
        } catch {
            thrown = true;
        }

        expect(thrown).toBe(true);
        expect(records.map((r) => r.id)).toEqual(originalOrder);
    });
});

// computeResequencePlan — shared pure plan (also consumed by static_list_sort)

describe("computeResequencePlan", () => {
    const getSequence = (r) => r.sequence;

    test("partial reorder on monotonic sequences only touches the moved span", () => {
        const records = makeRecords([
            [1, 10],
            [2, 20],
            [3, 30],
            [4, 40],
        ]);

        const plan = computeResequencePlan({
            records,
            movedId: 1,
            targetId: 3, // move record 1 after record 3
            getSequence,
        });

        expect(plan.reorderAll).toBe(false);
        // Only records 2, 3 and the moved record 1 are rewritten — 4 is untouched
        expect(plan.toReorder.map((r) => r.id)).toEqual([2, 3, 1]);
        expect(plan.offset).toBe(10);
        expect(plan.fromIndex).toBe(0);
        expect(plan.toIndex).toBe(2);
        // Pure: the input array is not mutated
        expect(records.map((r) => r.id)).toEqual([1, 2, 3, 4]);
    });

    test("non-monotonic (duplicate) sequences force a full reorder", () => {
        const records = makeRecords([
            [1, 10],
            [2, 10],
            [3, 10],
        ]);

        const plan = computeResequencePlan({
            records,
            movedId: 3,
            targetId: null,
            getSequence,
        });

        expect(plan.reorderAll).toBe(true);
        expect(plan.toReorder.map((r) => r.id)).toEqual([3, 1, 2]);
    });

    test("a record with an undefined sequence forces a full reorder", () => {
        const records = [
            { id: 1, sequence: 10 },
            { id: 2 }, // no sequence value
            { id: 3, sequence: 30 },
        ];

        const plan = computeResequencePlan({
            records,
            movedId: 3,
            targetId: 1,
            getSequence,
        });

        expect(plan.reorderAll).toBe(true);
        expect(plan.toReorder.length).toBe(3);
    });

    test("offset ignores null/NaN sequence values", () => {
        const records = [
            { id: 1, sequence: null },
            { id: 2, sequence: 7 },
            { id: 3, sequence: 12 },
        ];

        const plan = computeResequencePlan({
            records,
            movedId: 3,
            targetId: null,
            getSequence,
        });

        // null coerces to 0 in Math.min — it must be filtered out, so the
        // offset comes from the real numeric sequences (7), not 0.
        expect(plan.offset).toBe(7);
    });

    test("offset falls back to 0 when no record has a numeric sequence", () => {
        const records = [{ id: 1 }, { id: 2 }];

        const plan = computeResequencePlan({
            records,
            movedId: 2,
            targetId: null,
            getSequence,
        });

        expect(plan.offset).toBe(0);
    });

    test("descending order reverses the write order", () => {
        const records = makeRecords([
            [1, 30],
            [2, 20],
            [3, 10],
        ]);

        const plan = computeResequencePlan({
            records,
            movedId: 1,
            targetId: 2, // move first record after the second one
            getSequence,
            asc: false,
        });

        expect(plan.reorderAll).toBe(false);
        // Visual order after the move is [2, 1, 3]; writes are emitted in
        // ascending sequence order, i.e. reversed for a descending list.
        expect(plan.toReorder.map((r) => r.id)).toEqual([1, 2]);
        expect(plan.offset).toBe(20);
    });
});

// Descending order

describe("resequence — descending order", () => {
    test("asc=false reverses the sequence direction", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([
            [1, 30],
            [2, 20],
            [3, 10],
        ]);

        await resequence({
            records,
            resModel: "x",
            orm,
            fieldName: "sequence",
            movedId: 1,
            targetId: 3,
            asc: false,
        });

        expect(orm.calls.length).toBe(1);
    });
});
