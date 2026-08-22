/** @odoo-module native */

/**
 * @template T
 * @param {string | false | null | undefined} raw
 * @param {T} fallback
 * @param {string} [label]
 * @returns {T | any}
 */
export function parseJsonValue(raw, fallback, label = "") {
    if (!raw) {
        return fallback;
    }
    try {
        return JSON.parse(raw);
    } catch (error) {
        console.warn(
            `[stock] ${label || "field"} does not hold valid JSON; using the fallback:`,
            error,
        );
        return fallback;
    }
}

const CACHE = new WeakMap();

/**
 * @param {object} owner
 * @param {string | false | null | undefined} raw
 * @param {any} fallback
 * @param {string} [label]
 */
export function readJsonValue(owner, raw, fallback, label = "") {
    let entry = CACHE.get(owner);
    if (!entry || entry.raw !== raw) {
        entry = { raw, value: parseJsonValue(raw, fallback, label) };
        CACHE.set(owner, entry);
    }
    return entry.value;
}

export function readJsonField(component, fallback = {}) {
    const { record, name } = component.props;
    return readJsonValue(component, record.data[name], fallback, name);
}
