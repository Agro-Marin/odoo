/** @odoo-module native */
import { patch } from "@web/core/utils/patch";

import { PaymentForm } from "@payment/interactions/payment_form";

patch(PaymentForm.prototype, {
    /**
     * @override
     */
    _isPayLaterPaymentMethod(paymentMethodCode) {
        return (
            paymentMethodCode === "pay_on_site" ||
            super._isPayLaterPaymentMethod(...arguments)
        );
    },
});
