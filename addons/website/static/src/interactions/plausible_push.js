/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class PlausiblePush extends Interaction {
    static selector = ".js_plausible_push";

    setup() {
        const { eventName, eventParams } = this.el.dataset;

        window.plausible ||= function () {
            (window.plausible.q = window.plausible.q || []).push(arguments);
        };
        let props;
        try {
            props = JSON.parse(eventParams) || {};
        } catch {
            props = {};
        }
        window.plausible(eventName, { props });
    }
}

registry.category("public.interactions").add("website.plausible_push", PlausiblePush);
