import { expect, test } from "@odoo/hoot";
import { SMLX2ManyField } from "@stock/fields/stock_move_line_x2_many_field";
import { makeMockEnv, onRpc } from "@web/../tests/web_test_helpers";

async function makeField(moveLines, { recordResId = 100, recordDirty = false } = {}) {
    const env = await makeMockEnv();
    const field = Object.create(SMLX2ManyField.prototype);
    field.orm = env.services.orm;
    field.dirtyQuantsData = new Map();
    field.props = {
        record: {
            resId: recordResId,
            dirty: recordDirty,
            data: {
                product_uom_qty: 10,
                move_line_ids: { records: moveLines },
            },
        },
    };
    return field;
}

const moveLine = ({ resId, quantity, dirty = false, quantId = false }) => ({
    resId,
    dirty,
    data: { quant_id: quantId ? { id: quantId } : false, quantity },
});

test("pending lines are sent verbatim and availability comes back per quant", async () => {
    const lines = [
        moveLine({ resId: 11, quantity: 3, dirty: true }),
        moveLine({ resId: 12, quantity: 4, quantId: 201 }),
        moveLine({ resId: false, quantity: 2, quantId: 202 }),
    ];
    onRpc("get_pending_quant_availability", ({ args }) => {
        expect.step("availability-rpc");
        expect(args).toEqual([
            100,
            [
                { id: 11, quantity: 3, quant_id: false },
                { id: 12, quantity: 4, quant_id: 201 },
                { id: false, quantity: 2, quant_id: 202 },
            ],
        ]);
        return [
            [201, 8],
            [202, 11],
        ];
    });
    const field = await makeField(lines);
    await field.updateDirtyQuantsData();
    expect.verifySteps(["availability-rpc"]);
    expect(field.dirtyQuantsData.get(201)).toEqual({ available_quantity: 8 });
    expect(field.dirtyQuantsData.get(202)).toEqual({ available_quantity: 11 });
});

test("a fully consumed quant is reported, not omitted", async () => {
    // onAdd() needs these to build the `not in` half of the picker domain.
    onRpc("get_pending_quant_availability", () => [
        [201, 0],
        [202, -3],
    ]);
    const field = await makeField([moveLine({ resId: 11, quantity: 5, dirty: true })]);
    await field.updateDirtyQuantsData();
    expect(field.dirtyQuantsData.get(201).available_quantity).toBe(0);
    expect(field.dirtyQuantsData.get(202).available_quantity).toBe(-3);
});

test("the round trip is skipped when the form holds nothing new", async () => {
    onRpc("get_pending_quant_availability", () => {
        expect.step("availability-rpc");
        return [];
    });
    const field = await makeField([moveLine({ resId: 11, quantity: 5 })]);
    await field.updateDirtyQuantsData();
    expect.verifySteps([]);
    expect(field.dirtyQuantsData.size).toBe(0);
});

test("a deleted line dirties the move, so the round trip still happens", async () => {
    onRpc("get_pending_quant_availability", () => {
        expect.step("availability-rpc");
        return [[201, 6]];
    });
    // Every surviving line is clean; only the parent record records the deletion.
    const field = await makeField([moveLine({ resId: 11, quantity: 5 })], {
        recordDirty: true,
    });
    await field.updateDirtyQuantsData();
    expect.verifySteps(["availability-rpc"]);
    expect(field.dirtyQuantsData.get(201)).toEqual({ available_quantity: 6 });
});

test("availability is consumed in the move's UoM, with no client-side conversion", async () => {
    // The move is written in Dozens; the server has already converted. The client
    // must use the number as given -- this is the regression that the old
    // client-side arithmetic got wrong by the UoM factor.
    onRpc("get_pending_quant_availability", () => [[201, 2.5]]);
    const field = await makeField([
        moveLine({ resId: 11, quantity: 0.5, dirty: true }),
    ]);
    await field.updateDirtyQuantsData();
    expect(field.dirtyQuantsData.get(201).available_quantity).toBe(2.5);

    let created = null;
    // `list` is a getter on X2ManyField.prototype, so shadow it on the instance.
    Object.defineProperty(field, "list", {
        value: {
            addNewRecord: async (params) => {
                created = params;
                return { dirty: false };
            },
        },
    });
    await field.selectRecord([201]);
    // demand = product_uom_qty(10) - sum(quantities)(0.5) = 9.5, availability 2.5.
    expect(created.context.default_quantity).toBe(2.5);
});
