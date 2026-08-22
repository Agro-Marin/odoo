// @ts-check
/** @odoo-module native */

import { assetLog } from "@web/core/utils/asset_log";

/**
 * @type {Record<string, any>}
 */
export const session = /** @type {any} */ (odoo).__session_info__ || {};
assetLog(
    "session",
    "captured __session_info__ keys=",
    Object.keys(session).length,
    "uid=",
    session.uid,
    "db=",
    session.db,
);
