/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.shared_popup");

export class SharedPopup extends Interaction {
    static selector = ".s_popup";
    dynamicContent = {
        _root: {
            "t-on-show.bs.modal.noUpdate": () => {
                this.popupShown = true;
                this.updateContent();
            },
            "t-on-shown.bs.modal": () => (this.popupShown = true),
            "t-on-hidden.bs.modal": this.onModalHidden,
            "t-att-class": () => ({ "d-none": !this.popupShown }),
        },
    };

    setup() {
        log.lifecycle("SharedPopup setup", () => ({ id: this.el.id }));
        this.popupShown = false;
    }

    onModalHidden() {
        if (this.el.querySelector(".s_popup_no_backdrop")) {
            log.logic(
                "SharedPopup onModalHidden: no backdrop, dispatch scroll",
                () => ({
                    id: this.el.id,
                }),
            );
            window.dispatchEvent(new Event("scroll"));
        }
        this.popupShown = false;
    }
}

registry.category("public.interactions").add("website.shared_popup", SharedPopup);
