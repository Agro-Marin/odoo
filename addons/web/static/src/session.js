/** @module @web/session - Server-provided session data injected by the Odoo HTTP controller */

/** @type {Record<string, any>} */
export const session = odoo.__session_info__ || {};
delete odoo.__session_info__;
