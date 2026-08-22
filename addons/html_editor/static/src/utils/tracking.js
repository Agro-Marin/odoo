/** @odoo-module native */
export function trackOccurrences() {
    const visited = new Set();
    return function isFirstOccurrence(key) {
        if (visited.has(key)) {
            return false;
        }
        visited.add(key);
        return true;
    };
}

export function trackOccurrencesPair() {
    const visited = new Map();
    /** @type {(a, b) => boolean} */
    return function isFirstOccurrence(a, b) {
        if (!visited.has(a)) {
            visited.set(a, trackOccurrences());
        }
        return visited.get(a)(b);
    };
}
