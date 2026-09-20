/** @odoo-module native */

import { makeLogger } from "@web/core/debug/debug_logger";
import publicBootPromise from "@web/public/public_boot_instance";

const log = makeLogger("website.content.website_root");

const prom = publicBootPromise.then(async (env) => {
    log.lifecycle("public root booted", () => ({ inIframe: !!window.frameElement }));
    if (window.frameElement) {
        log.lifecycle("PUBLIC-ROOT-READY dispatched to parent frame");
        window.dispatchEvent(new CustomEvent("PUBLIC-ROOT-READY", { detail: { env } }));
    }
    return env;
});
export default prom;
