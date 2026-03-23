/** @odoo-module native */
import { ProfileEditor } from "./profile_editor.js";
import { registry } from "@web/core/registry";

const ProfileEditorEdit = I => class extends I {
    setup() { }
    async willStart() { }
};

registry
    .category("public.interactions.edit")
    .add("website_profile.website_profile_editor", {
        Interaction: ProfileEditor,
        mixin: ProfileEditorEdit,
    });
