/** @odoo-module native */
import { registry } from "@web/core/registry";
import { GallerySlider } from "@website/snippets/s_image_gallery/gallery_slider";

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
