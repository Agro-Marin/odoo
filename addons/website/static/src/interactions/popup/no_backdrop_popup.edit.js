/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { NoBackdropPopup } from "@website/interactions/popup/no_backdrop_popup";

const log = makeLogger("website.interaction.no_backdrop_popup.edit");

export const NoBackdropPopupEdit = (I) =>
    class extends I {
        start() {
            super.start();
            if (this.el.classList.contains("show")) {
                log.logic(
                    "NoBackdropPopupEdit start: already shown, attach events",
                    () => ({
                        id: this.el.id,
                    }),
                );
                this.addModalNoBackdropEvents();
            }
        }

        addModalNoBackdropEvents() {
            if (this.resizeObserver) {
                this.removeResizeListener();
                this.resizeObserver.disconnect();
                log.logic(
                    "NoBackdropPopupEdit re-attach: dropped previous observer",
                    () => ({
                        id: this.el.id,
                    }),
                );
            }
            super.addModalNoBackdropEvents();
        }
    };

registry.category("public.interactions.edit").add("website.no_backdrop_popup", {
    Interaction: NoBackdropPopup,
    mixin: NoBackdropPopupEdit,
});
