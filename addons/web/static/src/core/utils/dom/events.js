// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dom/events - Mark and query DOM events as handled during propagation */

const eventHandledWeakMap = new WeakMap();
/**
 * Returns whether the given event has been handled with the given markName.
 *
 * @param {Event} ev
 * @param {string} markName
 * @returns {boolean}
 */
export function isEventHandled(ev, markName) {
    const marks = eventHandledWeakMap.get(ev);
    return marks ? marks.includes(markName) : false;
}
/**
 * Marks the given event as handled by the given markName. Useful to allow
 * handlers in the propagation chain to make a decision based on what has
 * already been done.
 *
 * @param {Event} ev
 * @param {string} markName
 */
export function markEventHandled(ev, markName) {
    let marks = eventHandledWeakMap.get(ev);
    if (!marks) {
        marks = [];
        eventHandledWeakMap.set(ev, marks);
    }
    marks.push(markName);
}
