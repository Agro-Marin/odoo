/** @odoo-module native */

import { press } from "@odoo/hoot-dom";

/**
 * Type a barcode one key at a time, the way a scanner emits it.
 *
 * Use this when the keydown pipeline itself is under test -- the buffering,
 * the inter-key timeout, the editable-target filter. When a test only needs a
 * scan to have happened, `env.services.barcode.scan(barcode)` says so directly
 * and does not depend on that pipeline.
 *
 * @param {string[]} chars keys to press, e.g. [..."12345670", "Enter"]
 */
export async function simulateBarCode(chars) {
    for (const char of chars) {
        await press(char);
    }
}
