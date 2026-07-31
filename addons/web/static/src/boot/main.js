// @ts-check
/** @odoo-module native */

/** @module @web/boot/main */

import { paintBootFailureOverlay, startWebClient } from "@web/boot/start";
import { assetLog } from "@web/core/utils/asset_log";
import { WebClient } from "@web/webclient/webclient";

assetLog("boot", "main.js module evaluated — calling startWebClient(WebClient)");
startWebClient(/** @type {any} */ (WebClient)).catch((error) => {
    assetLog("boot", "startWebClient rejected", { error });
    paintBootFailureOverlay(error);
});
