import { expect } from "@odoo/hoot";
import { waitFor, waitForNone } from "@odoo/hoot-dom";

/**
 * @param {string} selector
 * @param {number} count
 */
export async function expectElementCount(selector, count) {
    if (count === 0) {
        await waitForNone(selector);
    } else {
        await waitFor(selector);
    }
    expect(selector).toHaveCount(count);
}
