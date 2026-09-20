/** @odoo-module native */
import { deserializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class Slides extends Interaction {
    static selector = "timeago.timeago";

    setup() {
        const datetime = this.el.getAttribute("datetime");
        const datetimeObj = deserializeDateTime(datetime);
        if (
            datetimeObj &&
            new Date().getTime() - datetimeObj.valueOf() > 7 * 24 * 60 * 60 * 1000
        ) {
            this.el.innerText = datetimeObj.toFormat("DD");
        } else {
            this.el.innerText = datetimeObj.toRelative();
        }
    }
}

registry.category("public.interactions").add("website_slides.slides", Slides);
