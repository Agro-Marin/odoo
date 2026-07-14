/** @odoo-module native */
import { Deferred } from "@web/core/utils/concurrency";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { memoize } from "@web/core/utils/functions";

odoo.portalChatterReady = new Deferred();

const loader = {
    loadChatter: memoize(() => loadBundle("portal.assets_chatter")),
};
export const portalChatterBootService = {
    start() {
        const chatterEl = document.querySelector(".o_portal_chatter");
        if (chatterEl) {
            loader.loadChatter();
        } else {
            // No chatter on this page: the lazy bundle that resolves the
            // Deferred will never load, so settle it here. Awaiters (e.g.
            // tours) get `false` instead of hanging forever.
            odoo.portalChatterReady.resolve(false);
        }
    },
};
registry.category("services").add("portal.chatter.boot", portalChatterBootService);
