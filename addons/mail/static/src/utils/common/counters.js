/** @odoo-module native */

/**
 * Counter helpers with bus-id fencing.
 *
 * Three counter families share the same convention: a counter field paired
 * with a `<field>_bus_id` companion recording the bus notification id of the
 * last applied absolute server snapshot:
 * - mailbox counters: `counter` on the inbox/starred/history mail.box threads,
 * - thread needaction: `message_needaction_counter` on Thread,
 * - channel member unread: `message_unread_counter` on discuss.channel.member
 *   (its `message_unread_counter_ui` companion is a UI-lagged copy maintained
 *   by a field onUpdate hook, not by these helpers).
 *
 * Fencing rules:
 * - an absolute snapshot (bus payload carrying the full counter value) is
 *   applied only when its bus id is newer than the last applied snapshot, and
 *   advances the bus id;
 * - an event-driven delta (bus payload describing a single transition) is
 *   applied only when its bus id is newer than the last absolute snapshot —
 *   an older-or-equal snapshot already accounts for the event. It does NOT
 *   advance the bus id: it is not a snapshot;
 * - an optimistic local delta ignores bus ids entirely;
 * - an optimistic rollback goes through a snapshot captured before the
 *   optimistic update, and is skipped when the bus id advanced in the
 *   meantime: a newer absolute snapshot must not be overwritten by a stale
 *   local value.
 */

/**
 * Apply an absolute counter snapshot, fenced by its bus id: ignored when
 * `busId` is not newer than the last applied snapshot. Advances the bus id.
 *
 * @param {Object} target record carrying `field` and `<field>_bus_id`
 * @param {string} field counter field name
 * @param {number} value absolute counter value from the snapshot
 * @param {number} busId bus notification id carrying the snapshot
 * @returns {boolean} whether the snapshot was applied
 */
export function applyCounterAbsolute(target, field, value, busId) {
    const busField = `${field}_bus_id`;
    if (busId <= target[busField]) {
        return false;
    }
    target[field] = value;
    target[busField] = busId;
    return true;
}

/**
 * Apply a relative counter change, clamped at `floor`. When `busId` is given
 * (event-driven delta), the change is fenced: ignored when `busId` is not
 * newer than the last absolute snapshot. Never advances the bus id. When
 * `busId` is omitted the delta is optimistic/local and always applies.
 *
 * @param {Object} target record carrying `field` and `<field>_bus_id`
 * @param {string} field counter field name
 * @param {number} delta relative change (positive or negative)
 * @param {Object} [options]
 * @param {number} [options.floor=0] lowest value the counter may reach
 * @param {number} [options.busId] bus notification id carrying the event
 * @returns {number} the delta actually applied (0 when fenced or clamped out)
 */
export function applyCounterDelta(target, field, delta, { floor = 0, busId } = {}) {
    if (busId !== undefined && busId <= target[`${field}_bus_id`]) {
        return 0;
    }
    const value = Math.max(target[field] + delta, floor);
    const applied = value - target[field];
    if (applied) {
        target[field] = value;
    }
    return applied;
}

/**
 * Capture a counter (value + bus id) before an optimistic update, for a
 * possible rollback. Both restore flavors are skipped when the bus id
 * advanced since the capture: a newer absolute snapshot supersedes any local
 * state, including the rollback.
 *
 * @param {Object} target record carrying `field` and `<field>_bus_id`
 * @param {string} field counter field name
 * @returns {{ restore: () => void, restoreDelta: (delta: number, options?: { floor?: number }) => void }}
 */
export function snapshotCounter(target, field) {
    const busField = `${field}_bus_id`;
    const value = target[field];
    const busId = target[busField];
    return {
        /** Restore the captured absolute value. */
        restore() {
            if (target[busField] === busId) {
                target[field] = value;
            }
        },
        /**
         * Re-apply a relative change (typically the inverse of the optimistic
         * delta), clamped at `floor`.
         *
         * @param {number} delta
         * @param {Object} [options]
         * @param {number} [options.floor=0]
         */
        restoreDelta(delta, { floor = 0 } = {}) {
            if (target[busField] === busId) {
                applyCounterDelta(target, field, delta, { floor });
            }
        },
    };
}
