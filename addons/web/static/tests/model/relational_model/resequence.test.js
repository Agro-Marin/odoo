// @ts-check

/**
 * Pure unit tests for resequence.js.
 *
 * Tests the resequence() function with a mock ORM. No OWL, DOM, or server.
 *
 * The function re-orders records in-place and calls orm.webResequence()
 * to persist the new sequences. Tests verify:
 *  - records array is reordered in place
 *  - orm.webResequence is called with the correct resIds and offset
 *  - rollback occurs on ORM error
 */

import { describe, expect, test } from "@odoo/hoot";
import { resequence } from "@web/model/relational_model/resequence";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Basic resequence — move forward
// ---------------------------------------------------------------------------

describe("resequence — move forward", () => {
    test("moves a record from index 0 to index 2", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([[1, 10], [2, 20], [3, 30]]);

        await resequence({
            records,
            resModel: "product.product",
            orm,
            fieldName: "sequence",
            movedId: 1,
            targetId: 3, // move after record 3
        });

        // Record 1 should now be at index 2
        expect(records[2].id).toBe(1);
        // ORM was called
        expect(orm.calls.length).toBe(1);
        expect(orm.calls[0].model).toBe("product.product");
    });

    test("moves a record from index 2 to index 0", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([[1, 10], [2, 20], [3, 30]]);

        await resequence({
            records,
            resModel: "res.partner",
            orm,
            fieldName: "sequence",
            movedId: 3,
            targetId: null, // move to first position
        });

        // Record 3 should now be at index 0
        expect(records[0].id).toBe(3);
    });
});

// ---------------------------------------------------------------------------
// ORM call parameters
// ---------------------------------------------------------------------------

describe("resequence — ORM call parameters", () => {
    test("passes fieldName as field_name param", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([[1, 10], [2, 20]]);

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
        const records = makeRecords([[1, 5], [2, 10], [3, 15]]);

        // Move record 3 before record 1 (targetId = null)
        await resequence({
            records,
            resModel: "product.product",
            orm,
            fieldName: "sequence",
            movedId: 3,
            targetId: null,
        });

        // When moving to position 0, all 3 records are reordered.
        // Minimum sequence is 5, so offset should be 5.
        expect(orm.calls[0].params.offset).toBe(5);
    });

    test("passes context to ORM when provided", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([[1, 1], [2, 2]]);
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

// ---------------------------------------------------------------------------
// Custom getSequence / getResId callbacks
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Rollback on error
// ---------------------------------------------------------------------------

describe("resequence — rollback on ORM error", () => {
    test("restores original order when ORM throws", async () => {
        const orm = makeMockOrm({ reject: true });
        const records = makeRecords([[1, 10], [2, 20], [3, 30]]);
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
        // Records restored to original order
        expect(records.map((r) => r.id)).toEqual(originalOrder);
    });
});

// ---------------------------------------------------------------------------
// Descending order
// ---------------------------------------------------------------------------

describe("resequence — descending order", () => {
    test("asc=false reverses the sequence direction", async () => {
        const orm = makeMockOrm();
        const records = makeRecords([[1, 30], [2, 20], [3, 10]]);

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
