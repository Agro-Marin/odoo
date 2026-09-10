// @ts-check

import { after } from "@odoo/hoot";

/** @param {() => void | Promise<void>} callback */
export function registerCleanup(callback) {
    after(callback);
}
