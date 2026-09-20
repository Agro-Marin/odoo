/** @odoo-module native */
import { MailGroup } from "@mail_group/interactions/mail_group";
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class MailGroupEdit extends Interaction {
    static selector = MailGroup.selector;
    dynamicContent = {
        _root: {
            "t-att-class": () => ({
                "d-none": false,
            }),
        },
    };
}

registry.category("public.interactions.edit").add("website_mail_group.mail_group", {
    Interaction: MailGroupEdit,
});
