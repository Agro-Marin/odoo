/** @odoo-module native */
import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

export class PortalDetails extends Interaction {
    static selector = ".o_portal_details";
    dynamicContent = {
        "select[name=country_id]": {
            "t-on-change": this.adaptAddressForm,
        },
    };

    setup() {
        this.stateEl = this.el.querySelector("select[name=state_id]");
        this.stateOptionEls = this.el.querySelectorAll(
            "select[name=state_id]:not([disabled]):not([disabled=false]) option:not(:first-child)"
        );
        this.adaptAddressForm();
    }

    adaptAddressForm() {
        const countryEl = this.el.querySelector("select[name=country_id]");
        // Keep this a string: `el.dataset.country_id` is always a string, and
        // mixing in a numeric 0 sentinel made the `===` below type-inconsistent.
        // "0" matches no real state option, preserving the "clear all" behavior
        // when no country is selected.
        const countryID = countryEl.value || "0";
        let nb = 0;
        for (const el of this.stateOptionEls) {
            if (el.dataset.country_id === countryID) {
                el.classList.remove("d-none");
                this.stateEl.appendChild(el);  // appendChild is a move when already attached
                nb++;
            } else {
                el.remove();
            }
        }
        this.stateEl.classList.remove("d-none");
        this.stateEl.parentElement.classList.toggle("d-none", nb === 0);
    }
}

registry.category("public.interactions").add("portal.portal_details", PortalDetails);
