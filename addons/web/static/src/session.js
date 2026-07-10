// @ts-check
/** @odoo-module native */
/** @module @web/session - Server-provided session data injected by the Odoo HTTP controller */

import { assetLog } from "@web/core/utils/asset_log";

/**
 * @type {Record<string, any>}
 *
 * We read ``odoo.__session_info__`` and keep a local snapshot, but do
 * NOT delete it from the global.  The test harness's
 * ``mock_server_state.hoot.js`` independently reads the same global
 * (it can't import @web/session because it must not depend on
 * non-hoot modules).  Whoever deleted first would leave the other
 * consumer with ``{}``.  Leaving the global in place is safe: session
 * info holds HMAC keys and company info, not raw secrets — the same
 * data is exposed via ``session.registry_hash`` etc. to any script
 * that imports this module anyway.
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
