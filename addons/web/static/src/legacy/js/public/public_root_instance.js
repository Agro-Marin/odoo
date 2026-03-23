// @ts-check
/** @odoo-module native */

/** @module @web/legacy/js/public/public_root_instance - Singleton PublicRoot widget instance creation and lazy-loader registration */

/** @odoo-module alias=root.widget */
import { PublicRoot, createPublicRoot } from "./public_root.js";
import lazyloader from "@web/legacy/js/public/lazyloader";

const prom = createPublicRoot(PublicRoot);
lazyloader.registerPageReadinessDelay(prom);
export default prom;
