/** @odoo-module native */
import { PaymentAdyen } from "@pos_adyen/app/utils/payment/payment_adyen";
import { patch } from "@web/core/utils/patch";
patch(PaymentAdyen.prototype, {
    _adyenPayData() {
        const data = super._adyenPayData(...arguments);

        if (data.SaleToPOIRequest.PaymentRequest.SaleData.SaleToAcquirerData) {
            data.SaleToPOIRequest.PaymentRequest.SaleData.SaleToAcquirerData +=
                "&authorisationType=PreAuth";
        } else {
            data.SaleToPOIRequest.PaymentRequest.SaleData.SaleToAcquirerData =
                "authorisationType=PreAuth";
        }

        return data;
    },

    sendPaymentAdjust(uuid) {
        const order = this.pos.getOrder();
        const line = order.getPaymentlineByUuid(uuid);
        const data = {
            originalReference: line.transaction_id,
            modificationAmount: {
                value: parseInt(
                    line.amount * Math.pow(10, this.pos.currency.decimal_places),
                ),
                currency: this.pos.currency.name,
            },
            merchantAccount: this.payment_method_id.adyen_merchant_account,
            additionalData: {
                industryUsage: "DelayedCharge",
            },
        };

        return this._callAdyen(data, "adjust");
    },

    canBeAdjusted(uuid) {
        const order = this.pos.getOrder();
        const line = order.getPaymentlineByUuid(uuid);
        return ["mc", "visa", "amex", "discover"].includes(line.card_type);
    },
});
