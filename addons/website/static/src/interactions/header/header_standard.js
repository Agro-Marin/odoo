/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { BaseHeader } from "@website/interactions/header/base_header";

const log = makeLogger("website.interaction.header_standard");

export class HeaderStandard extends BaseHeader {
    static selector = "header.o_header_standard:not(.o_header_sidebar)";

    setup() {
        super.setup();
        this.transitionPoint = 300;
        this.transitionPossible = false;
        log.lifecycle("HeaderStandard setup", () => ({
            transitionPoint: this.transitionPoint,
        }));
    }

    /**
     * @returns {boolean}
     */
    canTransition() {
        const scrollEl = this.scrollingElement;
        const remainingScroll =
            scrollEl.scrollHeight - scrollEl.clientHeight - this.transitionPoint;
        const clonedHeader = this.el.cloneNode(true);
        scrollEl.append(clonedHeader);
        clonedHeader.classList.add(
            "o_header_is_scrolled",
            "o_header_affixed",
            "o_header_no_transition",
        );
        const endHeaderHeight = clonedHeader.offsetHeight;
        clonedHeader.remove();
        const requiredScroll = this.getHeaderHeight() - endHeaderHeight;
        return requiredScroll > 0 ? remainingScroll > requiredScroll : true;
    }

    onScroll() {
        super.onScroll();

        const scroll = this.scrollingElement.scrollTop;

        const isScrolled = scroll > this.transitionPoint;
        if (this.isScrolled !== isScrolled) {
            this.transitionPossible = this.canTransition() || !isScrolled;
            log.pipeline("HeaderStandard onScroll: scrolled state change", () => ({
                from: this.isScrolled,
                to: isScrolled,
                transitionPossible: this.transitionPossible,
                scroll,
            }));
            if (this.transitionPossible) {
                this.adaptToHeaderChangeLoop(1);
            }
        }

        const reachHeaderBottom = scroll > this.getHeaderHeight() + this.topGap;
        const reachTransitionPoint =
            scroll > this.transitionPoint + this.topGap && this.transitionPossible;

        if (this.atTop === reachHeaderBottom) {
            this.el.classList.add("o_transformed_not_affixed");
        }
        this.el.style.transition = this.atTop === reachHeaderBottom ? "none" : "";
        this.atTop = !reachHeaderBottom;

        reachTransitionPoint
            ? this.transformShow()
            : reachHeaderBottom
              ? this.transformHide()
              : this.transformShow();
        void this.el.offsetWidth;

        this.hideEl?.classList.toggle("hidden", reachHeaderBottom);

        this.toggleCSSAffixed(reachHeaderBottom);
        this.el.classList.remove("o_transformed_not_affixed");
        this.isScrolled = reachTransitionPoint;
    }

    getHeaderHeight() {
        if (this.hideEl) {
            if (this.isSmall()) {
                return this.el.getBoundingClientRect().height;
            }
            if (this.hideEl.classList.contains("hidden")) {
                return this.hideElHeight + this.el.getBoundingClientRect().height;
            }
            this.hideElHeight = this.hideEl?.getBoundingClientRect().height;
        }
        return this.el.getBoundingClientRect().height;
    }
}

registry.category("public.interactions").add("website.header_standard", HeaderStandard);

registry.category("public.interactions.edit").add("website.header_standard", {
    Interaction: HeaderStandard,
});
