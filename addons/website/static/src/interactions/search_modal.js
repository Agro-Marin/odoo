/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Modal } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";

export class SearchModal extends Interaction {
    static selector = "#o_search_modal_block #o_search_modal";
    dynamicContent = {
        _root: {
            "t-on-shown.bs.modal": () => this.el.querySelector(".search-query").focus(),
        },
    };
    destroy() {
        Modal.getInstance(this.el)?.hide();
    }
}

registry.category("public.interactions").add("website.search_modal", SearchModal);
