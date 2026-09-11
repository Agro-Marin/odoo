/** @odoo-module native */
import { registry } from "@web/core/registry";
import { NoBackdropPopup } from "@website/interactions/popup/no_backdrop_popup";

export const NoBackdropPopupEdit = (I) =>
    class extends I {
        start() {
            super.start();
            if (this.el.classList.contains("show")) {
                this.addModalNoBackdropEvents();
            }
        }

        addModalNoBackdropEvents() {
            if (this.resizeObserver) {
                this.removeResizeListener();
                this.resizeObserver.disconnect();
            }
            super.addModalNoBackdropEvents();
        }
    };

registry.category("public.interactions.edit").add("website.no_backdrop_popup", {
    Interaction: NoBackdropPopup,
    mixin: NoBackdropPopupEdit,
});
