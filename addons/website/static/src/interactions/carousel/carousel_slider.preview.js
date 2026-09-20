/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Carousel } from "@web/libs/bootstrap";
import { CarouselSlider } from "@website/interactions/carousel/carousel_slider";

const CarouselSliderPreview = (I) =>
    class extends I {
        carouselOptions = { ride: true, pause: true, interval: 500 };

        dynamicSelectors = {
            ...this.dynamicSelectors,
            _snippetPreviewWrapEl: () => this.el.closest(".o_snippet_preview_wrap"),
        };
        dynamicContent = {
            ...this.dynamicContent,
            _snippetPreviewWrapEl: {
                "t-on-mouseenter": this.mouseEnter,
                "t-on-mouseleave": this.mouseLeave,
                "t-on-focusin": this.mouseEnter,
                "t-on-focusout": this.mouseLeave,
            },
        };

        mouseEnter() {
            const carousel = Carousel.getOrCreateInstance(this.el);
            carousel.cycle();
        }

        mouseLeave() {
            const carousel = Carousel.getOrCreateInstance(this.el);
            carousel.pause();
            carousel.to(0);
        }
    };

registry.category("public.interactions.preview").add("website.carousel_slider", {
    Interaction: CarouselSlider,
    mixin: CarouselSliderPreview,
});
