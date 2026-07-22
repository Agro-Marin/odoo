/** @odoo-module native */
import { registry } from "@web/core/registry";
import { isTrackedSnapshot } from "@website/core/website_edit_service";
import { DynamicSnippetCarousel } from "@website/snippets/s_dynamic_snippet_carousel/dynamic_snippet_carousel";

const DynamicSnippetCarouselEdit = (I) =>
    class extends I {
        getConfigurationSnapshot() {
            const snapshot = super.getConfigurationSnapshot();
            if (
                !isTrackedSnapshot(snapshot) ||
                !this.el.classList.contains("o_carousel_multi_items")
            ) {
                // `snapshot || "{}"` used to swallow the untracked sentinel,
                // converting "always restart" into a stable value. Forward it.
                return snapshot;
            }
            const parsed = JSON.parse(snapshot);
            parsed.multi_items = true;
            return JSON.stringify(parsed);
        }
    };

registry.category("public.interactions.edit").add("website.dynamic_snippet_carousel", {
    Interaction: DynamicSnippetCarousel,
    mixin: DynamicSnippetCarouselEdit,
});
