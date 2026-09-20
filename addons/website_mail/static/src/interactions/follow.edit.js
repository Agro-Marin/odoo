/** @odoo-module native */
import { Follow } from "@website_mail/interactions/follow";
import { registry } from "@web/core/registry";

const FollowEdit = (I) =>
    class extends I {
        dynamicContent = {};
    };

registry.category("public.interactions.edit").add("website_mail.follow", {
    Interaction: Follow,
    mixin: FollowEdit,
});
