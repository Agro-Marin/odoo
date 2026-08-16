/** @odoo-module native */
import { DonationSnippet } from "@website_payment/snippets/s_donation/donation_snippet";
import { registry } from "@web/core/registry";

const DonationSnippetEdit = I => class extends I {
    onDonateClick() { }
};

registry
    .category("public.interactions.edit")
    .add("website_payment.donation_snippet", {
        Interaction: DonationSnippet,
        mixin: DonationSnippetEdit,
    });
