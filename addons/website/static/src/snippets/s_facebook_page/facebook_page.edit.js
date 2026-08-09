/** @odoo-module native */
import { registry } from "@web/core/registry";
import { FacebookPage } from "@website/snippets/s_facebook_page/facebook_page";

const FacebookPageEdit = (I) =>
    class extends I {
        dynamicContent = {
            iframe: {
                "t-att-style": () => ({ "pointer-events": "none" }),
            },
        };
    };

registry.category("public.interactions.edit").add("website.facebook_page", {
    Interaction: FacebookPage,
    mixin: FacebookPageEdit,
});
