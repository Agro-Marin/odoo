/** @odoo-module native */

/**
 * Generate an identifier for a history node, a history step, a collaboration
 * peer or an embedded component.
 *
 * /!\ The decimal-digits-only format is load-bearing and must not be changed
 * for something more collision-resistant (``crypto.randomUUID()``, base36...).
 * Step ids are persisted inside the saved HTML as
 * ``data-last-history-steps="<id>,<id>,..."`` and are parsed back out by
 * digit-only regexes on both sides of the wire:
 *
 *   - ``html_editor/tools.py``                  ``data-last-history-steps="([0-9,]+)"``
 *   - ``collaboration_odoo_plugin.js``          ``/data-last-history-steps="([\d,]+)"/``
 *   - ``collaboration_odoo_plugin.js``          ``/data-last-history-steps="[0-9,]*?([0-9]+)"/``
 *
 * A non-numeric id would silently fail those matches on every document already
 * stored in the database, disabling the save-divergence check.
 *
 * Ordering note: peer ids are compared to break ties between concurrent steps
 * and to pick the "polite" peer during WebRTC negotiation. Those comparisons
 * must be plain codepoint comparisons, never ``localeCompare`` — see
 * ``compareIds``.
 *
 * @returns {string} a decimal string in [0, 2^52)
 */
export function generateId() {
    // No need for a cryptographically secure random number.
    return Math.floor(Math.random() * Math.pow(2, 52)).toString();
}

/**
 * Total order over ids, used to make independent peers agree on the same
 * ordering without communicating.
 *
 * Deliberately NOT ``String.prototype.localeCompare``: that is locale-sensitive
 * (Danish collates "aa" as "å", i.e. after "z") and ECMA-262 only specifies the
 * sign of its result, not its magnitude, so ``localeCompare(...) === 1`` is
 * unspecified behaviour. Two peers running different locales could disagree on
 * the order and diverge.
 *
 * @param {string} idA
 * @param {string} idB
 * @returns {number} negative, 0 or positive
 */
export function compareIds(idA, idB) {
    const a = String(idA);
    const b = String(idB);
    return a < b ? -1 : a > b ? 1 : 0;
}
