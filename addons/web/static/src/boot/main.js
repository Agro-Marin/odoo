// @ts-check
/** @odoo-module native */

/** @module @web/boot/main */

import { startWebClient } from "@web/boot/start";
import { paintBootFailureOverlay } from "@web/core/errors/boot_failure_overlay";
import { assetLog } from "@web/core/utils/asset_log";
import { WebClient } from "@web/webclient/webclient";

assetLog("boot", "main.js module evaluated — calling startWebClient(WebClient)");
startWebClient(/** @type {any} */ (WebClient)).catch((error) => {
    assetLog("boot", "startWebClient rejected", { error });
    paintBootFailureOverlay(error);
});
