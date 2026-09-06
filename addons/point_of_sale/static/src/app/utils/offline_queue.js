/** @odoo-module native */
export const UNSYNC_QUEUE_STORE = "pos.unsync.queue";

export function getQueueSequence(entry) {
    if (Number.isFinite(entry.sequence)) {
        return entry.sequence;
    }
    const timestamp = Date.parse(entry.date?.toISO?.() ?? entry.date);
    return Number.isFinite(timestamp) ? timestamp * 1000 : 0;
}

export function compareQueueEntries(a, b) {
    return getQueueSequence(a) - getQueueSequence(b) || a.uuid.localeCompare(b.uuid);
}
