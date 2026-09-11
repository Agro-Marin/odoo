/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class CarouselEdit extends Interaction {
    static selector = "section > .carousel";
    dynamicContent = {
        ".carousel-control-prev, .carousel-control-next, .carousel-indicators": {
            "t-on-click": this.throttled(this.onControlClick),
            "t-att-class": () => ({ o_we_no_overlay: true }),
        },
        ".carousel-control-prev, .carousel-control-next": {
            "t-att-data-bs-slide": () => undefined,
        },
        ".carousel-indicators > *": {
            "t-att-data-bs-slide-to": () => undefined,
        },
    };

    /**
     * @param {Event} ev
     */
    async onControlClick(ev) {
        this.el.querySelector(".carousel-item.active").click();

        const controlEl = ev.currentTarget;
        let direction;
        if (controlEl.classList.contains("carousel-control-prev")) {
            direction = "prev";
        } else if (controlEl.classList.contains("carousel-control-next")) {
            direction = "next";
        } else {
            const indicatorEl = ev.target;
            if (
                !indicatorEl.matches(".carousel-indicators > *") ||
                indicatorEl.classList.contains("active")
            ) {
                return;
            }
            direction = [...controlEl.children].indexOf(indicatorEl);
        }

        const applySpec = { editingElement: this.el, params: { direction: direction } };

        if (this.services["website_edit"].applyAction) {
            this.services["website_edit"].applyAction("slideCarousel", applySpec);
        }
    }

    destroy() {
        const editTranslations = this.services.website_edit.isEditingTranslations();
        if (!editTranslations) {
            const indicatorEls = this.el.querySelectorAll(".carousel-indicators > *");
            indicatorEls.forEach((indicatorEl, i) =>
                indicatorEl.setAttribute("data-bs-slide-to", i),
            );
        }
    }
}

registry.category("public.interactions.edit").add("website.carousel_edit", {
    Interaction: CarouselEdit,
});
