/** @odoo-module native */
// Bare, not relative: this `.edit` variant ships in an
// `assets_inside_builder_iframe` bundle that carries only the variant, while
// the class it extends ships in `web.assets_frontend` -- which the builder replays into
// the same iframe. A relative import made the browser fetch it as raw source
// instead of resolving it through that bundle's import map.
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
