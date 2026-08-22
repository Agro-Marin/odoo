/** @odoo-module native */
/**
 * @param {URLSearchParams} searchParams
 * @param {Number} orderTotal
 * @return {Boolean}
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
