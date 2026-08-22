// @ts-check
/** @odoo-module native */

import { startWebClient } from "@web/boot/start";
import { assetLog } from "@web/core/utils/asset_log";
import { WebClient } from "@web/webclient/webclient";

assetLog("boot", "main.js module evaluated — calling startWebClient(WebClient)");
startWebClient(WebClient);
