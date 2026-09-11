/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class TermsAndConditionsCheckbox extends Interaction {
    static selector = 'div[name="website_sale_terms_and_conditions_checkbox"]';
    dynamicContent = {
        "#website_sale_tc_checkbox": { "t-on-change": this.onClickTcCheckbox },
    };

    setup() {
        this.checkbox = this.el.querySelector("#website_sale_tc_checkbox");
    }

    /**
     * @return {void}
     */
    onClickTcCheckbox() {
        this.env.bus.trigger(
            this.checkbox.checked ? "enablePaymentButton" : "disablePaymentButton",
        );
    }
}

registry
    .category("public.interactions")
    .add("website_sale.terms_and_conditions_checkbox", TermsAndConditionsCheckbox);
