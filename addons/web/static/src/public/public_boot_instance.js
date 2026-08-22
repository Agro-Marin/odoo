// @ts-check
/** @odoo-module native */

import lazyloader from "@web/public/lazyloader";
import { startPublicApp } from "@web/public/public_boot";

const prom = startPublicApp();
lazyloader.registerPageReadinessDelay(prom);
prom.catch((error) => console.error("The public app failed to start:", error));
export default prom;
