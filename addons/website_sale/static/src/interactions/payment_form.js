/** @odoo-module native */
import { patch } from "@web/core/utils/patch";

import { PaymentForm } from "@payment/interactions/payment_form";

patch(PaymentForm.prototype, {
    /**
     * @override
     */
    setup() {
        super.setup();
        const submitButtons = document.querySelectorAll(
            'button[name="o_payment_submit_button"]',
        );
        submitButtons.forEach((submitButton) => {
            if (!this.el.contains(submitButton)) {
                submitButton.addEventListener("click", (ev) => this.submitForm(ev));
            }
        });
    },
});
