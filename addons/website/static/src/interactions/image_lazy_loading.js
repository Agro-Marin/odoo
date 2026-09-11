/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { onceAllImagesLoaded } from "@website/utils/images";

export class ImageLazyLoading extends Interaction {
    static selector = "#wrapwrap img[loading='lazy']";

    setup() {
        this.initialHeight = this.el.style.minHeight;
        this.el.style.minHeight = "1px";
    }

    start() {
        onceAllImagesLoaded(this.el).then(() => {
            if (!this.isDestroyed) {
                this.el.style.minHeight = this.initialHeight;
            }
        });
    }

    destroy() {
        this.el.style.minHeight = this.initialHeight;
    }
}

registry
    .category("public.interactions")
    .add("website.image_lazy_loading", ImageLazyLoading);
