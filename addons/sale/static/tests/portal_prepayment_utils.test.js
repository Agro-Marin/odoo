import { expect, test } from "@odoo/hoot";
import { computeIsDownPayment } from "@sale/interactions/portal_prepayment_utils";

const ORDER_TOTAL = 100;
const params = (search) => new URLSearchParams(search);

test("explicit amount_selection wins", () => {
    expect(
        computeIsDownPayment(params("amount_selection=down_payment"), ORDER_TOTAL),
    ).toBe(true);
    expect(
        computeIsDownPayment(params("amount_selection=full_amount"), ORDER_TOTAL),
    ).toBe(false);
});

test("malformed amount_selection falls through to the heuristic (server parity)", () => {
    // falls through to the payment_amount / default heuristic.
    expect(
        computeIsDownPayment(
            params("amount_selection=xyz&payment_amount=40"),
            ORDER_TOTAL,
        ),
    ).toBe(true);
    expect(computeIsDownPayment(params("amount_selection=xyz"), ORDER_TOTAL)).toBe(
        true,
    );
});

test("no amount_selection: payment_amount is compared to the order total", () => {
    expect(computeIsDownPayment(params("payment_amount=40"), ORDER_TOTAL)).toBe(true);
    expect(computeIsDownPayment(params("payment_amount=100"), ORDER_TOTAL)).toBe(false);
    expect(computeIsDownPayment(params("payment_amount=120"), ORDER_TOTAL)).toBe(false);
});

test("no choice and no amount defaults to a down payment", () => {
    expect(computeIsDownPayment(params(""), ORDER_TOTAL)).toBe(true);
});
