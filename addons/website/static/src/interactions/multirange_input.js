/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import multirange from "@website/../lib/multirange/multirange_custom";

const log = makeLogger("website.interaction.multirange_input");

export class MultirangeInput extends Interaction {
    static selector = "input[type=range][multiple]:not(.multirange)";

    start() {
        log.lifecycle("MultirangeInput start: init multirange", () => ({
            name: this.el.name,
        }));
        multirange.init(this.el);
    }
}

registry
    .category("public.interactions")
    .add("website.multirange_input", MultirangeInput);
