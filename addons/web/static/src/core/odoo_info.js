// @ts-check
/** @odoo-module native */

import { session } from "@web/session";

/**
 * @returns {boolean}
 */
export function publishOdooInfo() {
    const isEnterprise = (session.server_version_info ?? []).at(-1) === "e";
    /** @type {typeof odoo} */ (odoo).info = {
        db: session.db,
        server_version: session.server_version,
        server_version_info: session.server_version_info,
        isEnterprise,
    };
    return isEnterprise;
}
