import { expect, test } from "@odoo/hoot";
import { ForecastedDetails } from "@stock/stock_forecasted/forecasted_details";

/**
 * The grouping/merge pipeline is pure (props in, plain members out): exercise
 * it on a bare prototype instance, without OWL mounting or services.
 */
function makeDetails(docs) {
    const details = Object.create(ForecastedDetails.prototype);
    details.props = { docs };
    details._groupLines();
    details._prepareLines();
    details._prepareData();
    details._mergeLines();
    return details;
}

const doc = (id, name) => ({ id, _name: "stock.picking", name });

function makeDocs() {
    // Product 7: two on-hand lines (one reserved) + a zero-qty free-stock line.
    // Product 9: one reconciled line, no free stock.
    const onHand1 = {
        product: { id: 7 },
        document_in: false,
        document_out: doc(1, "OUT1"),
        in_transit: false,
        replenishment_filled: true,
        quantity: 3,
        reservation: false,
        move_out: { id: 11, picking_id: { id: 1, priority: "0" } },
    };
    const onHand2 = {
        ...onHand1,
        document_out: doc(2, "OUT2"),
        quantity: 4,
        reservation: true,
        move_out: { id: 12, picking_id: { id: 2, priority: "0" } },
    };
    const freeStockZero = {
        product: { id: 7 },
        document_in: false,
        document_out: false,
        in_transit: false,
        replenishment_filled: true,
        quantity: 0,
        reservation: false,
        move_out: false,
    };
    const reconciled = {
        product: { id: 9 },
        document_in: doc(3, "IN1"),
        document_out: doc(4, "OUT3"),
        in_transit: false,
        replenishment_filled: true,
        quantity: 5,
        reservation: false,
        move_out: { id: 13, picking_id: { id: 4, priority: "0" } },
        receipt_date: "07/20/2026",
    };
    return {
        docs: {
            lines: [onHand1, onHand2, freeStockZero, reconciled],
            product: {
                7: { qty_available_virtual: 5, qty_free: 2, qty: { in: 0, out: 0 } },
                9: { qty_available_virtual: 5, qty_free: 0, qty: { in: 0, out: 0 } },
            },
            multiple_product: true,
            user_can_edit_pickings: true,
        },
        lines: { onHand1, onHand2, freeStockZero, reconciled },
    };
}

test("grouping and totals per product", () => {
    const { docs, lines } = makeDocs();
    const details = makeDetails(docs);

    expect(details.OnHandLinesPerProduct[7]).toEqual([lines.onHand1, lines.onHand2]);
    expect(details.ReconciledLinesPerProduct[9]).toEqual([lines.reconciled]);
    expect(details.OnHandTotalQty[7]).toBe(7);
    // Reserved quantities are excluded from the available total.
    expect(details.AvailableOnHandTotalQty[7]).toBe(3);
    expect(details.isOnHand(lines.onHand1)).toBe(true);
    expect(details.isOnHand(lines.reconciled)).toBe(false);
    expect(details.isReconciled(lines.reconciled)).toBe(true);
});

test("zero-quantity free stock line is dropped when other lines exist", () => {
    const { docs, lines } = makeDocs();
    makeDetails(docs);
    expect(docs.lines).not.toInclude(lines.freeStockZero);
    expect(docs.lines.length).toBe(3);
});

test("adjacent on-hand lines of a product merge into one rowspan", () => {
    const { docs } = makeDocs();
    const details = makeDetails(docs);
    // onHand1/onHand2 sit at indices 0-1 after the free-stock line removal.
    expect(details.mergesLinesData[0]).toEqual({ rowcount: 2, tot_qty: 7 });
    // The reconciled line of the other product does not extend the merge.
    expect(details.mergesLinesData[2]).toBe(undefined);
});

test("displayReserve takes the line index explicitly", () => {
    const { docs, lines } = makeDocs();
    const details = makeDetails(docs);
    // On-hand line: reservable regardless of the previous-line heuristic.
    expect(details.displayReserve(lines.onHand1, 0)).toBe(true);
    // Reconciled line of a product without free stock: not reservable.
    expect(details.displayReserve(lines.reconciled, 2)).toBe(false);
});
