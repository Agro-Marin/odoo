/** @odoo-module native */
import { registry } from "@web/core/registry";
import { getScrollingElement } from "@web/core/utils/dom/scrolling";
import { Interaction } from "@web/public/interaction";

export class AnimateOverflow extends Interaction {
    static selector = "#wrapwrap";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _scrollingElement: () => this.scrollingElement,
    };
    dynamicContent = {
        _scrollingElement: {
            "t-att-class": () => ({
                o_wanim_overflow_xy_hidden:
                    this.forceOverflowXYHidden || this.hasAnimationInProgress,
            }),
        },
        _root: {
            "t-on-updatecontent.noUpdate": (ev) => {
                if (ev.target.classList.contains("o_animate")) {
                    this.updateContent();
                }
            },
        },
    };

    setup() {
        this.scrollingElement = getScrollingElement(this.el.ownerDocument);
        const animatedElements = this.el.querySelectorAll(".o_animate");
        this.forceOverflowXYHidden = [...animatedElements].some(
            (el) => window.getComputedStyle(el).transform !== "none",
        );
    }

    get hasAnimationInProgress() {
        return this.el.querySelector(".o_animating") != null;
    }
}

registry
    .category("public.interactions")
    .add("website.animate_overflow", AnimateOverflow);

registry.category("public.interactions.edit").add("website.animate_overflow", {
    Interaction: AnimateOverflow,
});
