/** @odoo-module native */

import publicBootPromise from "@web/public/public_boot_instance";

/**
 * When the page runs inside the website builder preview iframe, hand the
 * page's public env over to the builder (it needs the iframe's services,
 * e.g. `website_edit`). Historical event name kept from the PublicRoot era.
 */
const prom = publicBootPromise.then(async (env) => {
    if (window.frameElement) {
        window.dispatchEvent(new CustomEvent("PUBLIC-ROOT-READY", { detail: { env } }));
    }
    return env;
});
export default prom;
