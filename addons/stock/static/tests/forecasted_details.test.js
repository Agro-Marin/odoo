import { expect, test } from "@odoo/hoot";
import {
    classifyLine,
    ForecastedDetails,
} from "@stock/stock_forecasted/forecasted_details";

function makeDetails(docs) {
    const details = Object.create(ForecastedDetails.prototype);
    details.props = { docs };
    details._deriveLinesData(docs);
    return details;
}

const doc = (id, name) => ({ id, _name: "stock.picking", name });

function makeDocs() {
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

    expect(details.linesOf(7, "onHand")).toEqual([lines.onHand1, lines.onHand2]);
    expect(details.linesOf(9, "reconciled")).toEqual([lines.reconciled]);
    expect(details.onHandTotalQty[7]).toBe(7);
    expect(details.availableOnHandTotalQty[7]).toBe(3);
    expect(details.isOnHand(lines.onHand1)).toBe(true);
    expect(details.isOnHand(lines.reconciled)).toBe(false);
    expect(details.isReconciled(lines.reconciled)).toBe(true);
});

test("zero-quantity free stock line is dropped when other lines exist", () => {
    const { docs, lines } = makeDocs();
    const details = makeDetails(docs);
    expect(details.lines).not.toInclude(lines.freeStockZero);
    expect(details.lines.length).toBe(3);
});

test("the indexes are rebuilt after a line is dropped", () => {
    // The drop used to run after the grouping, leaving the removed line
    // reachable through it -- an invariant nothing asserted.
    const { docs, lines } = makeDocs();
    const details = makeDetails(docs);
    expect(details.linesOf(7, "freeStock")).toEqual([]);
    expect(details.categoryOf(lines.freeStockZero)).toBe(null);
    for (const category of ["onHand", "reconciled", "freeStock", "notAvailable"]) {
        for (const productId of details.productIds) {
            expect(details.linesOf(productId, category).length).toBe(
                details.lines.filter(
                    (l) =>
                        l.product.id === productId &&
                        details.categoryOf(l) === category,
                ).length,
            );
        }
    }
});

test("derivation never mutates the parent-owned docs.lines", () => {
    const { docs, lines } = makeDocs();
    const original = [...docs.lines];
    const details = makeDetails(docs);
    expect(details.lines).not.toBe(docs.lines);
    expect(docs.lines).toEqual(original);
    expect(docs.lines).toInclude(lines.freeStockZero);
});

test("re-deriving from new docs replaces the local line list", () => {
    const { docs } = makeDocs();
    const details = makeDetails(docs);
    const firstLines = details.lines;
    const { docs: newDocs } = makeDocs();
    newDocs.lines = newDocs.lines.slice(0, 2);
    details._deriveLinesData(newDocs);
    expect(details.lines).not.toBe(firstLines);
    expect(details.lines.length).toBe(2);
});

test("adjacent on-hand lines of a product merge into one rowspan", () => {
    const { docs } = makeDocs();
    const details = makeDetails(docs);
    expect(details.mergedRows[0]).toEqual({ rowcount: 2, tot_qty: 7 });
    expect(details.mergedRows[2]).toBe(undefined);
});

test("displayReserve takes the line index explicitly", () => {
    const { docs, lines } = makeDocs();
    const details = makeDetails(docs);
    expect(details.displayReserve(lines.onHand1, 0)).toBe(true);
    expect(details.displayReserve(lines.reconciled, 2)).toBe(false);
});

// The four predicates this replaced were mutually exclusive but not exhaustive.
// An incoming document with no matched demand fell through all of them -- 17 of
// 169 lines on an ordinary product -- so it had no name and no bucket.
test("classifyLine covers the whole reachable truth table", () => {
    const line = (document_in, in_transit, replenishment_filled, document_out) => ({
        document_in,
        in_transit,
        replenishment_filled,
        document_out,
    });
    expect(classifyLine(line(false, false, true, true))).toBe("onHand");
    expect(classifyLine(line(true, false, true, true))).toBe("reconciled");
    expect(classifyLine(line(false, false, true, false))).toBe("freeStock");
    expect(classifyLine(line(false, false, false, true))).toBe("notAvailable");
    expect(classifyLine(line(true, false, true, false))).toBe("incoming");
    expect(classifyLine(line(false, true, true, true))).toBe("inTransit");
    // Still unclassified, exactly as the scans left them.
    expect(classifyLine(line(true, false, false, true))).toBe(null);
    expect(classifyLine(line(false, false, false, false))).toBe(null);
});

test("an incoming line with no demand is classified, not silently ungrouped", () => {
    const incoming = {
        product: { id: 7 },
        document_in: doc(5, "IN2"),
        document_out: false,
        in_transit: false,
        replenishment_filled: true,
        quantity: 2,
        reservation: false,
        move_out: false,
        receipt_date: "07/21/2026",
    };
    const { docs } = makeDocs();
    docs.lines = [...docs.lines, incoming];
    const details = makeDetails(docs);
    expect(details.categoryOf(incoming)).toBe("incoming");
    expect(details.linesOf(7, "incoming")).toEqual([incoming]);
    expect(details.isOnHand(incoming)).toBe(false);
    expect(details.isReconciled(incoming)).toBe(false);
});
