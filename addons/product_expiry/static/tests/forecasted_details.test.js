import { expect, test } from "@odoo/hoot";
import "@product_expiry/forecasted_details";
import { ForecastedDetails } from "@stock/stock_forecasted/forecasted_details";

function makeDetails(docs) {
    const details = Object.create(ForecastedDetails.prototype);
    details.props = { docs };
    details._deriveLinesData(docs);
    return details;
}

const freeStockLine = (quantity, removal_date) => ({
    product: { id: 7 },
    document_in: false,
    document_out: false,
    in_transit: false,
    replenishment_filled: true,
    quantity,
    removal_date,
    reservation: false,
    move_out: false,
});

function makeDocs(undatedQty) {
    const expired = freeStockLine(2, -1);
    const undated = freeStockLine(undatedQty, false);
    const dated1 = freeStockLine(3, "09/10/2026");
    const dated2 = freeStockLine(4, "09/11/2026");
    return {
        docs: {
            lines: [expired, undated, dated1, dated2],
            product: {
                7: { qty_available_virtual: 9, qty_free: 9, qty: { in: 0, out: 0 } },
            },
            multiple_product: false,
            use_expiration_date: true,
            user_can_edit_pickings: true,
        },
        lines: { expired, undated, dated1, dated2 },
    };
}

test("expired stock is not free stock", () => {
    const { docs, lines } = makeDocs(10);
    const details = makeDetails(docs);

    expect(details.categoryOf(lines.expired)).toBe(null);
    expect(details.linesOf(7, "freeStock")).toEqual([
        lines.undated,
        lines.dated1,
        lines.dated2,
    ]);
});

test("dated removals are deducted from the undated free stock line", () => {
    const { docs, lines } = makeDocs(10);
    const details = makeDetails(docs);

    expect(lines.undated.quantity).toBe(3);
    expect(details.lines.length).toBe(4);
});

test("the undated free stock line is dropped once it is emptied", () => {
    const { docs, lines } = makeDocs(7);
    const details = makeDetails(docs);

    expect(details.lines).not.toInclude(lines.undated);
    expect(details.lines.length).toBe(3);
});

test("free stock lines merge with each other but not with expired stock", () => {
    const { docs } = makeDocs(10);
    const details = makeDetails(docs);

    expect(details.mergedRows[0]).toBe(undefined);
    expect(details.mergedRows[1]).toEqual({ rowcount: 3, tot_qty: 10 });
});
