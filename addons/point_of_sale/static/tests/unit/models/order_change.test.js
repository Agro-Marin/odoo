import { expect, test } from "@odoo/hoot";
import { getOrderChanges } from "@point_of_sale/app/models/utils/order_change";
import { getFilledOrder, setupPosEnv } from "../utils.js";
import { definePosModels } from "../data/generate_model_definitions.js";

definePosModels();

test("qty + note changed together keeps the qty delta on the ticket", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const line = order.lines[0];
    const categIds = new Set(line.product_id.parentPosCategIds);

    order.updateLastOrderChange();
    const sentQty = line.getQuantity();

    line.setQuantity(sentQty + 1);
    line.setNote("extra sauce");

    const changes = getOrderChanges(order, categIds);
    // The NEW-items entry must carry the qty delta — the shared-object
    // aliasing bug overwrote it with the previously-sent quantity.
    expect(changes.orderlines[line.uuid].quantity).toBe(1);
    // The note-update entry carries the previously sent quantity.
    expect(changes.noteUpdate[line.uuid].quantity).toBe(sentQty);
});

test("a note-only edit counts as a pending change", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const line = order.lines[0];
    const categIds = new Set(line.product_id.parentPosCategIds);

    order.updateLastOrderChange();
    line.setNote("no onions");

    const changes = getOrderChanges(order, categIds);
    // Consumers gate the order button / floor badges on nbrOfChanges; a
    // note-only edit used to leave it at 0 while still printing a ticket.
    expect(changes.nbrOfChanges).toBe(1);
    expect(changes.noteUpdate[line.uuid].quantity).toBe(line.getQuantity());
});
