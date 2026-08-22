import { describe, expect, test } from "@odoo/hoot";
import { uuidv4 } from "@point_of_sale/utils";
import { makeMockServer } from "@web/../tests/web_test_helpers";
import { luxon } from "@web/core/l10n/luxon";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getRelatedModelsInstance } from "../data/get_model_definitions.js";

const { DateTime } = luxon;

definePosModels();

describe("Dirty record", () => {
    test("field update", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const order = models["pos.order"].create({});
        expect(order.isDirty()).toBe(true);
        order.amount_total = 23.5;
        models.serializeForORM(order, { orm: true });

        expect(order.isDirty()).toBe(false);
        order.amount_total = 23.5;
        expect(order.isDirty()).toBe(false);
        order.amount_total = 25;
        expect(order.isDirty()).toBe(true);
        models.serializeForORM(order, { orm: true });
        expect(order.isDirty()).toBe(false);

        order.update({ amount_total: 26 });
        expect(order.isDirty()).toBe(true);
    });

    test("model creation", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const order = models["pos.order"].create({ id: 12 });
        expect(order.isDirty()).toBe(false);

        order.amount_total = 23.5;
        expect(order.isDirty()).toBe(true);
    });

    test("load data", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const sampleUUID = uuidv4();

        models.loadConnectedData({
            "pos.order": [
                {
                    id: 13,
                    amount_total: 30,
                    uuid: sampleUUID,
                },
            ],
        });

        const order = models["pos.order"].getBy("uuid", sampleUUID);
        expect(order.id).toBe(13);
        expect(order.amount_total).toBe(30);
        expect(order.isDirty()).toBe(false);
    });

    test("related record update", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const order = models["pos.order"].create({ id: 12 });
        expect(order.isDirty()).toBe(false);

        function clearOrder() {
            models.serializeForORM(order, { orm: true });
            expect(order.isDirty()).toBe(false);
        }

        const line = models["pos.order.line"].create({
            qty: 1,
            order_id: order,
        });
        expect(line.isDirty()).toBe(true);
        expect(order.isDirty()).toBe(true);
        clearOrder();
        expect(line.isDirty()).toBe(false);

        const sampleProduct = models["product.product"].create({
            name: "demo_product",
            id: 111,
        });
        line.product_id = sampleProduct;
        expect(line.isDirty()).toBe(true);
        expect(order.isDirty()).toBe(true);
        clearOrder();
        expect(line.isDirty()).toBe(false);

        line.qty = 10;
        expect(line.isDirty()).toBe(true);
        expect(order.isDirty()).toBe(true);
        clearOrder();

        order.lines[0].qty = 1000;
        expect(line.isDirty()).toBe(true);
        expect(order.isDirty()).toBe(true);
        clearOrder();

        line.product_id = null;
        expect(order.isDirty()).toBe(true);
        clearOrder();

        line.delete();
        expect(order.isDirty()).toBe(true);
        expect(order.lines.length).toBe(0);
    });

    test("many2many", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const order = models["pos.order"].create({ id: 12 });
        function clearOrder() {
            models.serializeForORM(order, { orm: true });
            expect(order.isDirty()).toBe(false);
        }
        const att1 = models["product.template.attribute.value"].create({ id: 99 });
        const line = models["pos.order.line"].create({
            id: 100,
            order_id: order,
            qty: 1,
        });
        line.update({ attribute_value_ids: [["link", att1]] });
        expect(line.isDirty()).toBe(true);
        expect(order.isDirty()).toBe(true);

        clearOrder();
        const att2 = models["product.template.attribute.value"].create({ id: 999 });
        line.update({ attribute_value_ids: [["link", att2]] });
        expect(line.isDirty()).toBe(true);
        expect(order.isDirty()).toBe(true);

        clearOrder();
        line.update({ attribute_value_ids: [["unlink", att1]] });
        expect(line.isDirty()).toBe(true);
        expect(order.isDirty()).toBe(true);
    });

    test("datetime type", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const order = models["pos.order"].create({ id: 12 });
        function clearOrder() {
            models.serializeForORM(order, { orm: true });
            expect(order.isDirty()).toBe(false);
        }
        expect(order.isDirty()).toBe(false);

        order.date_order = undefined;
        expect(order.isDirty()).toBe(false);

        clearOrder();
        order.date_order = DateTime.local(2025, 1, 1, 9, 30);
        expect(order.isDirty()).toBe(true);

        clearOrder();
        order.date_order = DateTime.local(2025, 1, 1, 9, 30);
        expect(order.isDirty()).toBe(false);

        clearOrder();
        order.date_order = DateTime.local(2028, 1, 1, 10, 30);
        expect(order.isDirty()).toBe(true);

        clearOrder();
        order.date_order = false;
        expect(order.isDirty()).toBe(true);

        clearOrder();
        order.date_order = null;
        expect(order.isDirty()).toBe(false);
    });

    test("edits made during a deferred sync survive the commit", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const order = models["pos.order"].create({ id: 12 });
        order.amount_total = 10;
        expect(order.isDirty()).toBe(true);

        const clearActions = [];
        models.serializeForORM(order, { deferClear: true, clearActions });
        order.amount_total = 20;
        clearActions.forEach((fn) => fn());
        expect(order.isDirty()).toBe(true);

        const clearActions2 = [];
        models.serializeForORM(order, {
            deferClear: true,
            clearActions: clearActions2,
        });
        clearActions2.forEach((fn) => fn());
        expect(order.isDirty()).toBe(false);
    });

    test("delete commands added during a deferred sync survive the commit", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const order = models["pos.order"].create({ id: 12 });
        const line1 = models["pos.order.line"].create({ id: 101, order_id: order });
        const line2 = models["pos.order.line"].create({ id: 102, order_id: order });
        expect(line1.isSynced).toBe(true);

        line1.delete({ backend: true });
        const clearActions = [];
        const serialized = models.serializeForORM(order, {
            deferClear: true,
            clearActions,
        });
        expect(serialized.lines).toInclude([2, 101]);

        line2.delete({ backend: true });
        clearActions.forEach((fn) => fn());

        const again = models.serializeForORM(order, {});
        expect(again.lines).toInclude([2, 102]);
        expect(again.lines).not.toInclude([2, 101]);
    });
});

test("restored __dirty marker marks the record dirty (isolated)", async () => {
    await makeMockServer();
    const models = getRelatedModelsInstance(false);
    const sampleUUID = uuidv4();
    models.loadConnectedData({
        "pos.order": [{ id: 13, uuid: sampleUUID, __dirty: true }],
    });
    expect(models["pos.order"].getBy("uuid", sampleUUID).isDirty()).toBe(true);
});
