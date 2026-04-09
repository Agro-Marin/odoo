/** @odoo-module native */
/** @module @web/session - Server-provided session data injected by the Odoo HTTP controller */

/** @type {Record<string, any>} */
export const session = odoo.__session_info__ || {};
// Do NOT delete __session_info__: when esbuild compiles multiple ESM
// bundles (e.g. web.assets_web + web.assets_tests), each bundle gets
// its own copy of session.js.  Deleting the global after the first
// bundle consumes it leaves subsequent bundles with an empty session,
// breaking edition detection, user context, and other session-dependent
// logic in test tour code.  The global is harmless to retain.
