// @ts-check
/** @odoo-module native */

/** @module @web/public/public_boot_instance - Boots the public app and gates page readiness on it */

import lazyloader from "@web/public/lazyloader";
import { startPublicApp } from "@web/public/public_boot";

const prom = startPublicApp();
lazyloader.registerPageReadinessDelay(prom);
// a boot failure leaves the page without services and without the `is-ready`
// flag every tour and the website builder wait on. Nothing here holds this
// promise, so report it rather than let it surface as a bare unhandled
// rejection that names nothing.
prom.catch((error) => console.error("The public app failed to start:", error));
export default prom;
