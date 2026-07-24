// @ts-check
/** @odoo-module native */

/** @module @web/public/public_boot_instance - Boots the public app and gates page readiness on it */

import lazyloader from "@web/public/lazyloader";
import { startPublicApp } from "@web/public/public_boot";

const prom = startPublicApp();
lazyloader.registerPageReadinessDelay(prom);
export default prom;
