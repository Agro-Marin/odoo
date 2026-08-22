/** @odoo-module native */
import { startPublicReadonlySpreadsheet } from "./boot.js";

// Entry point only. The sequence lives in `boot.js` because this file is
// `remove`d from `web.assets_unit_tests` — it self-executes, and importing it
// into a test page would boot a second spreadsheet app.
startPublicReadonlySpreadsheet();
