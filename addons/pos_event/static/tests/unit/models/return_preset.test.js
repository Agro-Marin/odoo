import { describe, expect, test } from "@odoo/hoot";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";

import { definePosEventModels } from "../data/generate_model_definitions.js";

definePosEventModels();

// CHARACTERIZATION OF A DEFECT, NOT OF DESIRED BEHAVIOUR. `setPreset` flips
// every line negative for a return preset and discards what `setQuantity`
// answers; `pos_event` refuses every quantity change on a ticket line. The
// order is left holding both signs at once, which is the state
// `pos_blackbox_be` raises "It is not allowed to mix refunds and sales" for.
// Whether returning a ticket should flip the line, cancel the registration or
// refuse the preset outright is an event-semantics decision that has not been
// taken; this test exists so that taking it is a deliberate act with a visible
// failure here, rather than a silent change to a behaviour nothing pinned.
describe("switching an order to a return preset", () => {
    test("the event ticket line keeps the sign every other line just lost", async () => {
        const store = await setupPosEnv();
        const order = store.addNewOrder();
        const product = store.models["product.template"].get(5);

        const plainLine = store.models["pos.order.line"].create({
            order_id: order,
            product_id: product.product_variant_ids[0],
            qty: 2,
            price_unit: 10,
        });
        const ticketLine = store.models["pos.order.line"].create({
            order_id: order,
            product_id: product.product_variant_ids[0],
            qty: 1,
            price_unit: 10,
            event_ticket_id: store.models["event.event.ticket"].get(1),
        });

        const preset = store.models["pos.preset"].get(1);
        preset.is_return = true;
        order.setPreset(preset);

        expect(plainLine.qty).toBe(-2);
        expect(ticketLine.qty).toBe(1);
        expect(order.lines.some((l) => l.qty > 0)).toBe(true);
        expect(order.lines.some((l) => l.qty < 0)).toBe(true);
    });
});
