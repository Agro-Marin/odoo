/** @odoo-module native */

/**
 * Parse a field that carries JSON in a char/text column.
 *
 * Four copies of this existed in `stock` alone -- two byte-identical bodies
 * differing only in the private field they cached into -- and they disagreed on
 * failure: two threw, one returned `[]`, one returned `null`. Malformed JSON in
 * a column is a server-side defect, and taking down the form it renders in does
 * not help anyone diagnose it, so every caller now degrades to its declared
 * fallback and says so in the console.
 *
 * @template T
 * @param {string | false | null | undefined} raw
 * @param {T} fallback
 * @param {string} [label] identifies the field in the console warning
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
 * The parsed value of the field this component renders, re-parsed only when the
 * raw string changes. Cached against the owner so re-reading it in several
 * getters during one render costs one parse.
 *
 * @param {object} owner the component, or any stable object identifying the read
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

/** The parsed JSON of the field a standard field component is bound to. */
export function readJsonField(component, fallback = {}) {
    const { record, name } = component.props;
    return readJsonValue(component, record.data[name], fallback, name);
}
