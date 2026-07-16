/** @odoo-module native */

import lazyloader from "@web/legacy/js/public/lazyloader";
import { createPublicRoot } from "@web/legacy/js/public/public_root";

import { WebsiteRoot } from "./website_root.js";

const prom = createPublicRoot(WebsiteRoot).then(async (rootInstance) => {
    if (window.frameElement) {
        window.dispatchEvent(
            new CustomEvent("PUBLIC-ROOT-READY", { detail: { rootInstance } }),
        );
    }
    return rootInstance;
});
lazyloader.registerPageReadinessDelay(prom);
export default prom;
