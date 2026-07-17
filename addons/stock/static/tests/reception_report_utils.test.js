import { expect, test } from "@odoo/hoot";
import {
    buildLabelAction,
    collectAssignable,
    collectAssignedLabels,
    isLineAssignable,
} from "@stock/components/reception_report_utils";

const line = (vals) => ({
    move_out_id: 1,
    quantity: 1,
    move_ins: [10],
    is_assigned: false,
    is_qty_assignable: true,
    ...vals,
});

test("isLineAssignable: unassigned and qty-assignable only", () => {
    expect(isLineAssignable(line())).toBe(true);
    expect(isLineAssignable(line({ is_assigned: true }))).toBe(false);
    expect(isLineAssignable(line({ is_qty_assignable: false }))).toBe(false);
    // "expected" draft lines expose is_qty_assignable: undefined
    expect(isLineAssignable(line({ is_qty_assignable: undefined }))).toBe(false);
});

test("collectAssignable accumulates only assignable lines, in order", () => {
    const lines = [
        line({ move_out_id: 1, quantity: 2, move_ins: [10] }),
        line({ move_out_id: 2, quantity: 3, move_ins: [11], is_assigned: true }),
        line({
            move_out_id: 3,
            quantity: 4,
            move_ins: false,
            is_qty_assignable: false,
        }),
        line({ move_out_id: 4, quantity: 5, move_ins: [12, 13] }),
    ];
    expect(collectAssignable(lines)).toEqual({
        moveIds: [1, 4],
        quantities: [2, 5],
        inIds: [[10], [12, 13]],
    });
});

test("collectAssignedLabels rounds quantities up and defaults to 1", () => {
    const lines = [
        line({ move_out_id: 1, quantity: 2.3, is_assigned: true }),
        line({ move_out_id: 2, quantity: 0, is_assigned: true }),
        line({ move_out_id: 3, quantity: 9 }), // not assigned: skipped
    ];
    expect(collectAssignedLabels(lines)).toEqual({
        docids: [1, 2],
        quantities: [3, 1],
    });
});

test("buildLabelAction builds the report action or null when empty", () => {
    expect(buildLabelAction({ id: 42 }, [], [])).toBe(null);
    expect(
        buildLabelAction({ id: 42, type: "ir.actions.report" }, [1, 2], [3, 1]),
    ).toEqual({
        id: 42,
        type: "ir.actions.report",
        context: { active_ids: [1, 2] },
        data: { docids: [1, 2], quantity: "3,1" },
    });
});
