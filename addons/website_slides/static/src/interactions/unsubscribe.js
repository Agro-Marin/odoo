/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

import { SlideUnsubscribeDialog } from "../js/public/components/slide_unsubscribe_dialog/slide_unsubscribe_dialog.js";

export class Unsubscribe extends Interaction {
    static selector = ".o_wslides_js_channel_unsubscribe";
    dynamicContent = {
        _root: {
            "t-on-click.prevent": () =>
                this.services.dialog.add(SlideUnsubscribeDialog, this.el.dataset),
        },
    };
}

registry.category("public.interactions").add("website_slides.unsubscribe", Unsubscribe);
