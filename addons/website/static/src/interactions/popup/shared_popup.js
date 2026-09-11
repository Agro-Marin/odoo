/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

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
        this.popupShown = false;
    }

    onModalHidden() {
        if (this.el.querySelector(".s_popup_no_backdrop")) {
            window.dispatchEvent(new Event("scroll"));
        }
        this.popupShown = false;
    }
}

registry.category("public.interactions").add("website.shared_popup", SharedPopup);
