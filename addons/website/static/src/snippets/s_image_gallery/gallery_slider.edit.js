/** @odoo-module native */
import { GallerySlider } from "./gallery_slider.js";
import { registry } from "@web/core/registry";

const GallerySliderEdit = (I) =>
    class extends I {
        setup() {
            super.setup();
            this.hideOnClickIndicator = false;
        }
    };

registry.category("public.interactions.edit").add("website.gallery_slider", {
    Interaction: GallerySlider,
    mixin: GallerySliderEdit,
});
