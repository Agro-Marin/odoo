import { expect, test } from "@odoo/hoot";
import { SMLX2ManyField } from "@stock/fields/stock_move_line_x2_many_field";
import { makeMockEnv, onRpc } from "@web/../tests/web_test_helpers";

/**
 * The quant-offset arithmetic of updateDirtyQuantsData is exercised on a bare
 * prototype instance wired to the mock env's real orm service (RPCs are
 * intercepted with onRpc): no OWL mounting, no relational model — the move
 * lines are shaped like Records (`data`, `resId`, private `_values`/`_changes`
 * as documented on _unsavedQtyDelta).
 */
async function makeField(moveLines, { recordResId = 100 } = {}) {
    const env = await makeMockEnv();
    const field = Object.create(SMLX2ManyField.prototype);
    field.orm = env.services.orm;
    field.dirtyQuantsData = new Map();
    field.props = {
        record: {
            resId: recordResId,
            data: { move_line_ids: { records: moveLines } },
        },
    };
    return field;
}

const moveLine = ({ resId, quantity, savedQuantity = quantity, quantId = false }) => ({
    resId,
    data: { quant_id: quantId ? { id: quantId } : false, quantity },
    _values: { quantity: savedQuantity },
    _changes: { quantity },
});

test("updateDirtyQuantsData combines unsaved qty deltas and quant reassignments", async () => {
    // ml 11: saved with qty 5, edited down to 3 (unsaved delta +2).
    // ml 12: now points at quant 201 with qty 4; in DB it consumed 4 from
    //        quant 202.
    // ml 13: untouched (delta 0 → not a dirty-quantity line).
    const lines = [
        moveLine({ resId: 11, quantity: 3, savedQuantity: 5 }),
        moveLine({ resId: 12, quantity: 4, quantId: 201 }),
        moveLine({ resId: 13, quantity: 7 }),
    ];
    onRpc("get_move_line_quant_match", ({ args }) => {
        expect.step("match-rpc");
        // [all saved line ids, parent move id, dirty saved line ids, quant ids]
        expect(args).toEqual([[11, 12, 13], 100, [11, 12], [201]]);
        return [
            [
                [201, { available_quantity: 10, move_line_ids: [11] }],
                [202, { available_quantity: 7, move_line_ids: [] }],
            ],
            [[12, { quantity: 4, quant_id: 202 }]],
        ];
    });
    const field = await makeField(lines);
    await field.updateDirtyQuantsData();
    expect.verifySteps(["match-rpc"]);
    // 201: +2 (unsaved delta of ml 11) - 4 (ml 12 now reserves from it) = 8.
    expect(field.dirtyQuantsData.get(201)).toEqual({ available_quantity: 8 });
    // 202: +4 given back by ml 12 leaving its DB quant = 11.
    expect(field.dirtyQuantsData.get(202)).toEqual({ available_quantity: 11 });
});

test("updateDirtyQuantsData skips the RPC when nothing is dirty", async () => {
    onRpc("get_move_line_quant_match", () => {
        expect.step("match-rpc");
        return [[], []];
    });
    const field = await makeField([
        moveLine({ resId: 11, quantity: 5 }), // unchanged: delta is 0
    ]);
    await field.updateDirtyQuantsData();
    // No dirty line: no RPC at all, and no leftover data from a previous run.
    expect.verifySteps([]);
    expect(field.dirtyQuantsData.size).toBe(0);
});

test("_unsavedQtyDelta is falsy for unchanged quantities (NaN included)", async () => {
    const field = await makeField([]);
    expect(Boolean(field._unsavedQtyDelta(moveLine({ resId: 1, quantity: 5 })))).toBe(
        false,
    );
    // A pristine record without tracked changes yields NaN — also falsy.
    const pristine = { _values: { quantity: 5 }, _changes: {} };
    expect(Boolean(field._unsavedQtyDelta(pristine))).toBe(false);
    expect(
        Boolean(
            field._unsavedQtyDelta(
                moveLine({ resId: 1, quantity: 3, savedQuantity: 5 }),
            ),
        ),
    ).toBe(true);
});
