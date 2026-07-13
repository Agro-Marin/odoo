/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { Popover } from "@web/libs/bootstrap";
import { registry } from "@web/core/registry";

import { parseDate } from "@web/core/l10n/dates";

export class ProjectRatingImage extends Interaction {
    static selector = ".o_portal_project_rating .o_rating_image";

    start() {
        const popover = Popover.getOrCreateInstance(this.el, {
            placement: "bottom",
            trigger: "hover",
            html: true,
            content: () => {
                const ratingEl = document.querySelector("#rating_" + this.el.dataset.id);
                if (!ratingEl) {
                    return "";
                }
                const duration = parseDate(this.el.dataset.ratingDate).toRelative();
                ratingEl.querySelector(".rating_timeduration").textContent = duration;
                return ratingEl.outerHTML;
            },
        });
        // Dispose on teardown so the Bootstrap instance and its hover listeners
        // on this.el don't leak when the interaction is destroyed/re-rendered.
        this.registerCleanup(() => popover.dispose());
    }
}

registry
    .category("public.interactions")
    .add("project.project_rating_image", ProjectRatingImage);
