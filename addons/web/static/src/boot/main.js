// @ts-check
/** @odoo-module native */

/** @module @web/boot/main - Entry point that launches the web client (replaced in enterprise) */

import { startWebClient } from "@web/boot/start";
import { assetLog } from "@web/core/utils/asset_log";
import { WebClient } from "@web/webclient/webclient";
/** Own file so enterprise can swap in its WebClient subclass. */

assetLog("boot", "main.js module evaluated — calling startWebClient(WebClient)");
startWebClient(/** @type {any} */ (WebClient));
