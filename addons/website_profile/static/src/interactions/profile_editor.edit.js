/** @odoo-module native */
// Bare, not relative: this `.edit` variant ships in an
// `assets_inside_builder_iframe` bundle that carries only the variant, while
// the class it extends ships in `web.assets_frontend` -- which the builder replays into
// the same iframe. A relative import made the browser fetch it as raw source
// instead of resolving it through that bundle's import map.
import { ProfileEditor } from "@website_profile/interactions/profile_editor";
import { registry } from "@web/core/registry";

const ProfileEditorEdit = (I) =>
    class extends I {
        setup() {}
        async willStart() {}
    };

registry
    .category("public.interactions.edit")
    .add("website_profile.website_profile_editor", {
        Interaction: ProfileEditor,
        mixin: ProfileEditorEdit,
    });
