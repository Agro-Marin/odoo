/** @odoo-module native */
import { registry } from "@web/core/registry";
import { isTrackedSnapshot } from "@website/core/website_edit_service";
import { TableOfContent } from "@website/snippets/s_table_of_content/table_of_content";

export const TableOfContentEdit = (I) =>
    class extends I {
        getConfigurationSnapshot() {
            const snapshot = super.getConfigurationSnapshot();
            if (
                !isTrackedSnapshot(snapshot) ||
                !this.el.classList.contains("s_table_of_content_horizontal_navbar")
            ) {
                // `snapshot || "{}"` used to swallow the untracked sentinel,
                // converting "always restart" into a stable value. Forward it.
                return snapshot;
            }
            const parsed = JSON.parse(snapshot);
            parsed.horizontalNavbar = true;
            return JSON.stringify(parsed);
        }
    };

registry.category("public.interactions.edit").add("website.table_of_content", {
    Interaction: TableOfContent,
    mixin: TableOfContentEdit,
});
