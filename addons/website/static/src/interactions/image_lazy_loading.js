/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { onceAllImagesLoaded } from "@website/utils/images";

const log = makeLogger("website.interaction.image_lazy_loading");

export class ImageLazyLoading extends Interaction {
    static selector = "#wrapwrap img[loading='lazy']";

    setup() {
        this.initialHeight = this.el.style.minHeight;
        this.el.style.minHeight = "1px";
    }

    start() {
        const endLoad = log.perf("ImageLazyLoading start: wait image load", () => ({
            src: this.el.getAttribute("src"),
        }));
        onceAllImagesLoaded(this.el).then(() => {
            endLoad(() => ({ isDestroyed: this.isDestroyed }));
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
