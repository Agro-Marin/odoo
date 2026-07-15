/** @odoo-module native */
/**
 * Decide whether the portal payment is a down payment, from the payment-link query
 * string. Pure and dependency-free so it can be unit-tested in isolation.
 *
 * Mirrors the server-side `SaleController._determine_is_down_payment`
 * (sale/controllers/portal.py): an explicit `amount_selection` wins; otherwise the
 * decision falls back to the payment amount vs. the order total. `prepayment_percent`
 * (the server's no-amount fallback) isn't exposed client-side, but these controls are
 * only rendered when a down payment is available (`prepayment_percent < 1.0`), so the
 * no-`payment_amount` case is always a down payment here.
 *
 * @param {URLSearchParams} searchParams The current query string.
 * @param {Number} orderTotal The order's total amount (`data-order-amount-total`).
 * @return {Boolean} Whether the current payment is a down payment.
 */
export function computeIsDownPayment(searchParams, orderTotal) {
    const amountSelection = searchParams.get("amount_selection");
    if (amountSelection === "down_payment") {
        return true;
    }
    if (amountSelection === "full_amount") {
        return false;
    }
    if (searchParams.has("payment_amount")) {
        return Number(searchParams.get("payment_amount")) < orderTotal;
    }
    return true;
}
