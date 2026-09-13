/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { SharedPopup } from "@website/interactions/popup/shared_popup";

const log = makeLogger("website.interaction.shared_popup.edit");

export const SharedPopupEdit = (I) =>
    class extends I {
        setup() {
            log.lifecycle("SharedPopupEdit setup", () => ({ id: this.el.id }));
            this.popupShown = true;
        }
    };

registry.category("public.interactions.edit").add("website.shared_popup", {
    Interaction: SharedPopup,
    mixin: SharedPopupEdit,
});
