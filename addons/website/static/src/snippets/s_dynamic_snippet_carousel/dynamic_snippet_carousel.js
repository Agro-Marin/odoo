/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { utils as uiUtils } from "@web/ui/viewport";
import { DynamicSnippet } from "@website/snippets/s_dynamic_snippet/dynamic_snippet";

const log = makeLogger("website.snippet.s_dynamic_snippet_carousel");

export class DynamicSnippetCarousel extends DynamicSnippet {
    static selector = ".s_dynamic_snippet_carousel";

    setup() {
        super.setup();
        this.templateKey = "website.s_dynamic_snippet.carousel";
    }

    getQWebRenderOptions() {
        const scrollMode = this.el.classList.contains("o_carousel_multi_items")
            ? "single"
            : "all";
        log.logic("getQWebRenderOptions: carousel options", () => ({
            scrollMode,
            interval: this.el.dataset.carouselInterval,
            rowPerSlide: this.el.dataset.rowPerSlide,
            arrowPosition: this.el.dataset.arrowPosition,
        }));
        return Object.assign(super.getQWebRenderOptions(...arguments), {
            interval: parseInt(this.el.dataset.carouselInterval),
            rowPerSlide: parseInt(
                uiUtils.isSmall() ? 1 : this.el.dataset.rowPerSlide || 1,
            ),
            arrowPosition: this.el.dataset.arrowPosition || "",
            scrollMode: scrollMode,
        });
    }
}

registry
    .category("public.interactions")
    .add("website.dynamic_snippet_carousel", DynamicSnippetCarousel);
