/** @odoo-module native */
import { registry } from "@web/core/registry";
import { AnnouncementScroll } from "@website/snippets/s_announcement_scroll/announcement_scroll";

export const AnnouncementScrollEdit = (I) =>
    class extends I {
        shouldStop() {
            return true;
        }
        isImpactedBy(el) {
            return (
                this.el.contains(el) &&
                el.matches(
                    `.s_announcement_scroll_marquee_container,
                    .s_announcement_scroll_marquee_item:first-child,
                    .s_announcement_scroll_marquee_item:first-child > [data-oe-translation-source-sha]`,
                )
            );
        }
    };

registry.category("public.interactions.edit").add("website.announcement_scroll", {
    Interaction: AnnouncementScroll,
    mixin: AnnouncementScrollEdit,
});
