import { describe, expect, test } from "@odoo/hoot";
import { makeMockServer } from "@web/../tests/web_test_helpers";

import { DataServiceOptions } from "@point_of_sale/app/models/data_service_options";
import { definePosModels } from "../data/generate_model_definitions.js";
import { getRelatedModelsInstance } from "../data/get_model_definitions.js";

definePosModels();

describe("AUDIT_CHALLENGE A2 reparenting stale inverse", () => {
    // Claim: connectNewData wholesale-replaces RAW_SYMBOL but never writes the
    // changed many2one into rawData, so _connect can't clean the old parent's
    // o2m. Reparenting a line from orderA to orderB leaves it in BOTH.
    test("A2: reparenting a line via connectNewData clears the old parent o2m", async () => {
        await makeMockServer();
        const models = getRelatedModelsInstance(false);
        const orderA = models["pos.order"].create({ id: 101 });
        const orderB = models["pos.order"].create({ id: 102 });
        const line = models["pos.order.line"].create({ id: 201, order_id: orderA });

        const lineIds = (o) => o.lines.map((l) => l.id);
        expect(lineIds(orderA)).toEqual([201]);
        expect(lineIds(orderB)).toEqual([]);

        // A server/device snapshot reparents the line to orderB. Match the
        // existing record by BOTH keys (databaseTable key for pos.order.line is
        // uuid) so we hit the existing-record update branch, not a create.
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

// CHALLENGE tests: each asserts the CORRECT behavior. A FAILURE confirms the
// audit finding is a real bug; a PASS falsifies my claim.

describe("AUDIT_CHALLENGE A3 purge asymmetry", () => {
    // Claim: pos.order keeps current-session paid orders, but pos.order.line /
    // pos.payment conditions lack the session check, so children are purged
    // while the parent order is kept -> header-with-no-lines corruption.
    test("A3: current-session paid order and its line/payment purge symmetrically", () => {
        const CUR = 1;
        globalThis.odoo = globalThis.odoo || {};
        odoo.pos_session_id = CUR;

        const tables = new DataServiceOptions().databaseTable;
        const orderCond = tables["pos.order"].condition;
        const lineCond = tables["pos.order.line"].condition;
        const payCond = tables["pos.payment"].condition;

        // A paid+synced order IN THE CURRENT session.
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

        // The order is (correctly) KEPT because it's the current session.
        expect(orderPurged).toBe(false);
        // Children MUST follow the parent: if the order is kept, its line and
        // payment must be kept too. If these purge while the order stays, the
        // order reloads as a header with no lines/payments.
        expect(linePurged).toBe(orderPurged); // line purge must match parent
        expect(payPurged).toBe(orderPurged); // payment purge must match parent
    });
});
