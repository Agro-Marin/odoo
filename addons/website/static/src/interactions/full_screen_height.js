/** @odoo-module native */
import { registry } from "@web/core/registry";
import { isVisible } from "@web/core/utils/dom/ui";
import { Interaction } from "@web/public/interaction";

export class FullScreenHeight extends Interaction {
    static selector = ".o_full_screen_height";
    dynamicContent = {
        _window: {
            "t-on-resize.noUpdate": this.debounced(this.updateContent, 250, {
                leading: true,
                trailing: true,
            }),
        },
        _root: {
            "t-att-style": () => ({
                "min-height": this.isActive
                    ? `${this.computeIdealHeight()}px !important`
                    : undefined,
            }),
        },
    };

    setup() {
        this.inModal = !!this.el.closest(".modal");
        const currentHeight = this.el.getBoundingClientRect().height;
        const idealHeight = this.computeIdealHeight();
        this.isActive = !isVisible(this.el) || currentHeight > idealHeight + 1;
    }

    computeIdealHeight() {
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        if (
            !this.smallestViewportHeight ||
            Math.abs(viewportWidth - this.previousViewportWidth) > 15 ||
            Math.abs(viewportHeight - this.previousViewportHeight) > 150
        ) {
            this.previousViewportWidth = viewportWidth;
            this.previousViewportHeight = viewportHeight;
            const el = document.createElement("div");
            el.classList.add("vh-100");
            el.style.position = "fixed";
            el.style.top = "0";
            el.style.pointerEvents = "none";
            el.style.visibility = "hidden";
            el.style.setProperty("height", "100svh", "important");
            document.body.appendChild(el);
            this.smallestViewportHeight = parseFloat(el.getBoundingClientRect().height);
            document.body.removeChild(el);
        }

        if (this.inModal) {
            return this.smallestViewportHeight;
        }

        const firstContentEl = this.el.ownerDocument.querySelector(
            "#wrapwrap > main > :first-child",
        );
        const mainTopPos =
            firstContentEl.getBoundingClientRect().top +
            this.el.ownerDocument.documentElement.scrollTop;
        return this.smallestViewportHeight - mainTopPos;
    }
}

registry
    .category("public.interactions")
    .add("website.full_screen_height", FullScreenHeight);
