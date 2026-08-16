/** @odoo-module native */

/**
 * @param {Object} target
 * @param {string} field
 * @param {number} value
 * @param {number} busId
 * @returns {boolean}
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
 * @param {Object} target
 * @param {string} field
 * @param {number} delta
 * @param {Object} [options]
 * @param {number} [options.floor=0]
 * @param {number} [options.busId]
 * @returns {number}
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
 * @param {Object} target
 * @param {string} field
 * @returns {{ restore: () => void, restoreDelta: (delta: number, options?: { floor?: number }) => void }}
 */
export function snapshotCounter(target, field) {
    const busField = `${field}_bus_id`;
    const value = target[field];
    const busId = target[busField];
    return {
        restore() {
            if (target[busField] === busId) {
                target[field] = value;
            }
        },
        /**
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
