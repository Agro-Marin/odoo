/** @odoo-module native */
import { registry } from "@web/core/registry";

import { DynamicSnippet } from "./dynamic_snippet.js";

const DynamicSnippetEdit = (I) =>
    class extends I {
        setup() {
            super.setup();
            this.withSample = true;
        }
        callToAction() {}
    };

registry.category("public.interactions.edit").add("website.dynamic_snippet", {
    Interaction: DynamicSnippet,
    mixin: DynamicSnippetEdit,
});
