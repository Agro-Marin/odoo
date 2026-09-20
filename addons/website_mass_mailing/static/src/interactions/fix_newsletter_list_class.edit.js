/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class fixNewsletterListClass extends Interaction {
    static selector =
        ".s_newsletter_subscribe_form:not(.s_subscription_list), .s_newsletter_block";
    dynamicContent = {
        _root: {
            "t-att-class": () => ({
                s_newsletter_list: true,
            }),
        },
    };
}

registry
    .category("public.interactions.edit")
    .add("website_mass_mailing.fix_newsletter_list_class", {
        Interaction: fixNewsletterListClass,
    });
