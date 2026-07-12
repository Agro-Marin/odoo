// @ts-check
/** @odoo-module native */

/** @module @web/boot/main - Entry point that launches the web client (replaced in enterprise) */

import { paintBootFailureOverlay, startWebClient } from "@web/boot/start";
import { assetLog } from "@web/core/utils/asset_log";
import { WebClient } from "@web/webclient/webclient";
/** Own file so enterprise can swap in its WebClient subclass. */

assetLog("boot", "main.js module evaluated — calling startWebClient(WebClient)");
// startWebClient paints its own failure surface for mount errors and swallows
// them; this .catch is the last-resort net for anything that escapes it (an
// error thrown before the mount try/catch, or from the catch itself) so a boot
// failure can never dangle as a bare unhandled rejection with no user feedback.
startWebClient(/** @type {any} */ (WebClient)).catch((error) => {
    assetLog("boot", "startWebClient rejected", { error });
    paintBootFailureOverlay(error);
});
