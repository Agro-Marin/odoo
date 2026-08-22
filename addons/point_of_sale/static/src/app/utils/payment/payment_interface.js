/** @odoo-module native */
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

    get fastPayments() {
        return true;
    }

    /**
     * @param {string} uuid
     * @returns {Promise}
     */
    sendPaymentRequest(uuid) {}

    /**
     * @param {} order
     * @param {string} uuid
     * @returns {Promise}
     */
    sendPaymentCancel(order, uuid) {}

    /**
     * @param {string} uuid
     * @returns {Promise}
     */
    sendPaymentReversal(uuid) {}

    close() {}
}
