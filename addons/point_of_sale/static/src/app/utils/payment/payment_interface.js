/** @odoo-module native */
/**
 * Implement this interface to support a new payment method in the POS, then
 * register it (`'my_payment'` is its technical name in use_payment_terminal):
 *
 * import { PaymentInterface } from "@point_of_sale/app/utils/payment/payment_interface";
 * import { register_payment_method } from "@point_of_sale/app/store/pos_store";
 * class MyPayment extends PaymentInterface {}
 * register_payment_method('my_payment', MyPayment);
 */
export class PaymentInterface {
    constructor(pos, payment_method_id) {
        this.setup(pos, payment_method_id);
    }

    setup(pos, payment_method_id) {
        this.env = pos.env;
        this.pos = pos;
        this.payment_method_id = payment_method_id;
        this.supports_reversals = false;
    }

    /**
     * This getter determines if send_payment_request
     * is called automatically upon selecting the payment method.
     * Overriding this to false allows manual input of an amount
     * before sending the request to the terminal.
     */
    get fastPayments() {
        return true;
    }

    /**
     * Called when the user clicks "Send". Initiates a payment request and sets
     * the line's final status via setPaymentStatus. On success, set the receipt
     * info via setReceiptInfo() and set card_type and transaction_id on the line.
     *
     * @param {string} uuid - The uuid of the paymentline
     * @returns {Promise} resolves to false when the payment should be retried;
     *   rejects when the paymentline status will be updated manually.
     */
    sendPaymentRequest(uuid) {}

    /**
     * Called when a user removes a payment line that's still waiting
     * on send_payment_request to complete. Should execute some
     * request to ensure the current payment request is
     * cancelled. This is not to refund payments, only to cancel
     * them. The payment line being cancelled will be deleted
     * automatically after the returned promise resolves.
     *
     * @param {} order - The order of the paymentline
     * @param {string} uuid - The id of the paymentline
     * @returns {Promise}
     */
    sendPaymentCancel(order, uuid) {}

    /**
     * This is an optional method. When implementing this make sure to
     * call enable_reversals() in the constructor of your
     * interface. This should reverse a previous payment with status
     * 'done'. The paymentline will be removed based on returned
     * Promise.
     *
     * @param {string} uuid - The id of the paymentline
     * @returns {Promise} returns true if the reversal was successful.
     */
    sendPaymentReversal(uuid) {}

    /**
     * Called when the payment screen in the POS is closed (by
     * e.g. clicking the "Back" button). Could be used to cancel in
     * progress payments.
     */
    close() {}
}
