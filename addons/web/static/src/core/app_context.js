// @ts-check
/** @odoo-module native */
import { useEnv } from "@odoo/owl";

/** @typedef {import("@web/core/service_container").ServiceContext} AppContext */

/** @returns {AppContext} */
export function useAppContext() {
    return /** @type {AppContext} */ (useEnv());
}
