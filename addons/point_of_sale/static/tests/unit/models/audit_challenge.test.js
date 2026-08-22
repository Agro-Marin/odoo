import { describe, expect, test } from "@odoo/hoot";
import { DataServiceOptions } from "@point_of_sale/app/models/data_service_options";
import { makeMockServer } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getRelatedModelsInstance } from "../data/get_model_definitions.js";

definePosModels();

describe("AUDIT_CHALLENGE A2 reparenting stale inverse", () => {
    test("A2: reparenting a line via connectNewData clears the old parent o2m", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const orderA = models["pos.order"].create({ id: 101 });
        const orderB = models["pos.order"].create({ id: 102 });
        const line = models["pos.order.line"].create({ id: 201, order_id: orderA });

        const lineIds = (o) => o.lines.map((l) => l.id);
        expect(lineIds(orderA)).toEqual([201]);
        expect(lineIds(orderB)).toEqual([]);

        models.connectNewData({
            "pos.order.line": [{ id: 201, uuid: line.uuid, order_id: 102 }],
        });

        expect({
            lineOrderId: line.order_id?.id,
            orderA: lineIds(orderA),
            orderB: lineIds(orderB),
        }).toEqual({ lineOrderId: 102, orderA: [], orderB: [201] });
    });
});

describe("AUDIT_CHALLENGE A3 purge asymmetry", () => {
    test("A3: current-session paid order and its line/payment purge symmetrically", () => {
        const CUR = 1;
        globalThis.odoo = globalThis.odoo || {};
        odoo.pos_session_id = CUR;

        const tables = new DataServiceOptions().databaseTable;
        const orderCond = tables["pos.order"].condition;
        const lineCond = tables["pos.order.line"].condition;
        const payCond = tables["pos.payment"].condition;

        const order = {
            finalized: true,
            isSynced: true,
            session_id: { id: CUR },
        };
        const line = { order_id: order };
        const payment = { pos_order_id: order };

        const orderPurged = orderCond(order);
        const linePurged = lineCond(line);
        const payPurged = payCond(payment);

        expect(orderPurged).toBe(false);
        expect(linePurged).toBe(orderPurged);
        expect(payPurged).toBe(orderPurged);
    });

    test("A3b: all four purge conditions agree with the parent order", () => {
        const CUR = 1;
        globalThis.odoo = globalThis.odoo || {};
        odoo.pos_session_id = CUR;

        const tables = new DataServiceOptions().databaseTable;
        const purgeAll = (order) => ({
            order: tables["pos.order"].condition(order),
            line: tables["pos.order.line"].condition({ order_id: order }),
            payment: tables["pos.payment"].condition({ pos_order_id: order }),
            customValue: tables["product.attribute.custom.value"].condition({
                order_id: order,
            }),
        });

        expect(
            purgeAll({
                finalized: true,
                isSynced: true,
                id: 7,
                session_id: { id: CUR },
            }),
        ).toEqual({ order: false, line: false, payment: false, customValue: false });

        expect(
            purgeAll({
                finalized: true,
                isSynced: true,
                id: 7,
                session_id: { id: CUR + 1 },
            }),
        ).toEqual({ order: true, line: true, payment: true, customValue: true });

        expect(
            purgeAll({ finalized: false, isSynced: false, session_id: { id: CUR } }),
        ).toEqual({ order: false, line: false, payment: false, customValue: false });

        expect(purgeAll(undefined)).toEqual({
            order: false,
            line: false,
            payment: false,
            customValue: false,
        });
    });
});
