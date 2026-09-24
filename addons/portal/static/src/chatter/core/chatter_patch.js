/** @odoo-module native */
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { patch } from "@web/core/utils/patch";

import { usePortalContext } from "../../portal_context.js";

Chatter.template = "portal.Chatter";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.portalContext = usePortalContext();
    },
});
