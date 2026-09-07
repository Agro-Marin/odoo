/** @odoo-module native */

/**
 * `pos.order.line.note` and `pos.order.internal_note` are Text columns on the
 * server, so a note reaches the client as whatever was written into it: the
 * JSON array the note editor produces, a plain sentence typed through the ORM,
 * or nothing. This is the one place that decides what each of those means.
 *
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
