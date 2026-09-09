// @ts-check
/** @odoo-module native */

/**
 * @param {string|Array|false|undefined} note
 * @returns {Array<{text: string, colorIndex?: number}>}
 */
export function parseNoteEntries(note) {
    if (!note) {
        return [];
    }
    if (Array.isArray(note)) {
        return note.map(toEntry);
    }
    if (typeof note !== "string") {
        return [];
    }
    let parsed;
    try {
        parsed = JSON.parse(note);
    } catch {
        return [{ text: note, colorIndex: 0 }];
    }
    return Array.isArray(parsed)
        ? parsed.map(toEntry)
        : [{ text: note, colorIndex: 0 }];
}

function toEntry(entry) {
    return typeof entry === "string" ? { text: entry, colorIndex: 0 } : entry;
}
