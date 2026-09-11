/** @odoo-module native */

import publicBootPromise from "@web/public/public_boot_instance";

const prom = publicBootPromise.then(async (env) => {
    if (window.frameElement) {
        window.dispatchEvent(new CustomEvent("PUBLIC-ROOT-READY", { detail: { env } }));
    }
    return env;
});
export default prom;
