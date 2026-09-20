/** @odoo-module native */
import { SupportedPaymentMethods } from "@website_payment/snippets/s_supported_payment_methods/supported_payment_methods";
import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";

const SupportedPaymentMethodsEdit = (I) =>
    class extends I {
        dynamicContent = {
            ".o_wpay_view_providers_btn": {
                "t-on-click": this.onClickViewProviders.bind(this),
            },
        };

        /**
         * @override
         */
        setup() {
            super.setup();
            this.templateKey =
                "website_payment.s_supported_payment_methods.no_payment_methods_alert";
        }

        async onClickViewProviders() {
            browser.open("/odoo/action-payment.action_payment_provider", "_blank");
        }
    };

registry.category("public.interactions.edit").add("website.supported_payment_methods", {
    Interaction: SupportedPaymentMethods,
    mixin: SupportedPaymentMethodsEdit,
});
