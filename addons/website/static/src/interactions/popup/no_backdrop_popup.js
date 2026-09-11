/** @odoo-module native */
import { registry } from "@web/core/registry";
import { isScrollableY } from "@web/core/utils/dom/scrolling";
import { Modal } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";

export class NoBackdropPopup extends Interaction {
    static selector = ".s_popup_no_backdrop";
    dynamicContent = {
        _root: {
            "t-on-shown.bs.modal": this.addModalNoBackdropEvents,
            "t-on-hide.bs.modal": this.removeModalNoBackdropEvents,
        },
    };

    setup() {
        this.throttledUpdateScrollbar = this.throttled(this.updateScrollbar);
        this.removeResizeListener = null;
        this.resizeObserver = null;
    }

    destroy() {
        this.removeModalNoBackdropEvents();
        window.dispatchEvent(new Event("resize"));
    }

    updateScrollbar() {
        const modalContentEl = this.el.querySelector(".modal-content");
        const isOverflowing = isScrollableY(modalContentEl);
        const bsModal = Modal.getOrCreateInstance(this.el);
        if (isOverflowing) {
            bsModal._adjustDialog();
        } else {
            bsModal._resetAdjustments();
        }
    }

    addModalNoBackdropEvents() {
        this.updateScrollbar();
        this.removeResizeListener = this.addListener(
            window,
            "resize",
            this.throttledUpdateScrollbar,
        );
        this.resizeObserver = new window.ResizeObserver(() => {
            this.updateScrollbar();
        });
        this.resizeObserver.observe(this.el.querySelector(".modal-content"));
    }

    removeModalNoBackdropEvents() {
        this.throttledUpdateScrollbar.cancel();
        if (this.resizeObserver) {
            this.removeResizeListener();
            this.resizeObserver.disconnect();
            delete this.resizeObserver;
        }
    }
}

registry
    .category("public.interactions")
    .add("website.no_backdrop_popup", NoBackdropPopup);
