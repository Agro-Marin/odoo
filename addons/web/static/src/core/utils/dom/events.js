// @ts-check
/** @odoo-module native */

const eventHandledWeakMap = new WeakMap();
/**
 * @param {Event} ev
 * @param {string} markName
 * @returns {boolean}
 */
export function isEventHandled(ev, markName) {
    const marks = eventHandledWeakMap.get(ev);
    return marks ? marks.includes(markName) : false;
}
/**
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
