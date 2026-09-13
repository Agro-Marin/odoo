/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { isVisible } from "@web/core/utils/dom/ui";
import { AnchorSlide } from "@website/interactions/anchor_slide";

const log = makeLogger("website.interaction.scroll_button");

export class ScrollButton extends AnchorSlide {
    static selector = ".o_scroll_button";

    animateClick() {
        const currentSectionEl = this.el.closest("section");
        let nextEl = currentSectionEl.nextElementSibling;
        while (nextEl) {
            if (isVisible(nextEl)) {
                log.logic(
                    "ScrollButton animateClick: scroll to next visible section",
                    () => ({
                        tagName: nextEl.tagName,
                        snippet: nextEl.dataset.snippet,
                    }),
                );
                this.scrollTo(nextEl);
                return;
            }
            nextEl = nextEl.nextElementSibling;
        }
        log.logic("ScrollButton animateClick: no visible next section", () => ({
            section: currentSectionEl.dataset.snippet,
        }));
    }
}

registry.category("public.interactions").add("website.scroll_button", ScrollButton);
