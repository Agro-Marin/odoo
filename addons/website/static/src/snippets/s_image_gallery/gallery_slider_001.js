/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.snippet.s_image_gallery.slider_001");

export class GallerySlider001 extends Interaction {
    static selector = ".o_slideshow[data-vcss='002']";
    dynamicContent = {
        ".carousel": {
            "t-on-slide.bs.carousel": this.onSlideCarousel,
        },
        ".carousel-indicators": {
            "t-on-scroll": this.checkScrollableIndicators,
            "t-att-class": () => ({
                o_faded_left: this.canScrollLeft,
                o_faded_right: this.canScrollRight,
            }),
        },
    };

    setup() {
        this.carouselEl = this.el.classList.contains("carousel")
            ? this.el
            : this.el.querySelector(".carousel");
        this.indicatorsWrapperEl =
            this.carouselEl?.querySelector(".carousel-indicators");
        log.lifecycle("setup", () => ({
            hasCarousel: !!this.carouselEl,
            hasIndicators: !!this.indicatorsWrapperEl,
            indicators:
                this.indicatorsWrapperEl?.querySelectorAll("[data-bs-slide-to]").length,
        }));

        if (this.indicatorsWrapperEl) {
            this.indicatorEls =
                this.indicatorsWrapperEl.querySelectorAll("[data-bs-slide-to]");

            if (this.indicatorEls.length) {
                const isRTL = !!this.el.closest(".o_rtl, [dir='rtl']");
                const nbIndicators = this.indicatorEls.length - 1;
                const index = {
                    left: isRTL ? nbIndicators : 0,
                    right: isRTL ? 0 : nbIndicators,
                };
                this.leftIndicatorEl = this.indicatorEls.item(index.left);
                this.rightIndicatorEl = this.indicatorEls.item(index.right);

                this.checkScrollableIndicators();
            }
        }
    }
    checkScrollableIndicators() {
        const containerRect = this.indicatorsWrapperEl.getBoundingClientRect();
        const leftIndicatorRect = this.leftIndicatorEl.getBoundingClientRect();
        const rightIndicatorRect = this.rightIndicatorEl.getBoundingClientRect();
        this.canScrollLeft = leftIndicatorRect.left < containerRect.left;
        this.canScrollRight = rightIndicatorRect.right > containerRect.right;
    }

    onSlideCarousel(ev) {
        if (this.indicatorEls.length) {
            log.logic("onSlideCarousel: scrolling indicators", () => ({ to: ev.to }));
            const nextActiveIndicatorEl = this.indicatorEls.item(ev.to);
            this.indicatorsWrapperEl.scrollTo({
                left:
                    nextActiveIndicatorEl.offsetLeft +
                    nextActiveIndicatorEl.offsetWidth / 2 -
                    this.indicatorsWrapperEl.offsetWidth / 2,
                behavior: "smooth",
            });
        }
    }
}

registry
    .category("public.interactions")
    .add("website.gallery_slider_001", GallerySlider001);
registry
    .category("public.interactions.edit")
    .add("website.gallery_slider_001", { Interaction: GallerySlider001 });
