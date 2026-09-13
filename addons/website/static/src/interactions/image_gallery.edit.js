/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.image_gallery.edit");

export class ImageGalleryEdit extends Interaction {
    static selector = ".s_image_gallery";
    static selectorNotHas =
        "img, a.o_link_readonly, span.fa.object-fit-cover, div.media_iframe_video";
    dynamicContent = {
        ".o_empty_gallery_alert": {
            "t-on-click": this.onAddImage.bind(this),
        },
    };
    start() {
        const endRender = log.perf(
            "ImageGalleryEdit start: render empty gallery alert",
        );
        this.renderAt("website.empty_image_gallery_alert", {}, this.el);
        endRender();
    }
    onAddImage() {
        const applySpec = { editingElement: this.el };
        log.logic("ImageGalleryEdit onAddImage: apply addImage", () => ({
            id: this.el.id,
        }));
        this.services["website_edit"].applyAction("addImage", applySpec);
    }
}

registry.category("public.interactions.edit").add("website.image_gallery_edit", {
    Interaction: ImageGalleryEdit,
});
