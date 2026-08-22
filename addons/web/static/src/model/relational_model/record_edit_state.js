// @ts-check
/** @odoo-module native */

import { markRaw } from "@odoo/owl";

/**
 * @typedef {{
 * changes: Record<string, any>,
 * textValues: Record<string, any>,
 * invalidFields: string[],
 * unsetRequiredFields: string[],
 * }} SavePoint
 */

/**
 * @param {{
 * changes?: Record<string, any>,
 * textValues?: Record<string, any>,
 * invalidFields?: Iterable<string>,
 * unsetRequiredFields?: Iterable<string>,
 * }} [parts]
 * @returns {SavePoint}
 */
export function createSavePoint({
    changes = {},
    textValues = {},
    invalidFields = [],
    unsetRequiredFields = [],
} = {}) {
    return markRaw({
        changes: { ...changes },
        textValues: { ...textValues },
        invalidFields: [...invalidFields],
        unsetRequiredFields: [...unsetRequiredFields],
    });
}

export class RecordEditState {
    constructor() {
        /**
         * @type {Record<string, any>}
         */
        this._changes = markRaw({});

        this.dirty = false;

        /**
         * @type {Set<string>}
         */
        this.invalidFields = new Set();
        /** @type {Set<string>} */
        this.unsetRequiredFields = markRaw(new Set());
        this.closeInvalidFieldsNotification = () => {};

        this.textValues = markRaw({});
        this.initialTextValues = markRaw({});

        this.savePoint = undefined;
    }

    /**
     * @returns {Record<string, any>}
     */
    get changes() {
        return this._changes;
    }

    /**
     * @param {Record<string, any>} initial
     */
    set changes(initial) {
        this._changes = markRaw(initial);
    }

    get isChangeSetEmpty() {
        return Object.keys(this._changes).length === 0;
    }

    /**
     * @returns {boolean}
     */
    get hasPendingChanges() {
        return this.dirty || !this.isChangeSetEmpty;
    }

    clearChanges() {
        this._changes = markRaw({});
        this.dirty = false;
    }

    commit() {
        this.clearChanges();
        this.initialTextValues = markRaw({ ...this.textValues });
    }

    rollback() {
        this.clearChanges();
        this.textValues = markRaw({ ...this.initialTextValues });
    }

    reset() {
        this.clearChanges();
        this.textValues = markRaw({});
        this.initialTextValues = markRaw({});
    }

    clearValidity() {
        this.invalidFields.clear();
        this.unsetRequiredFields.clear();
    }

    /**
     * @param {{ invalidFields: Iterable<string>, unsetRequiredFields: Iterable<string> }} snapshot
     */
    restoreValidity({ invalidFields, unsetRequiredFields }) {
        this.invalidFields = new Set(invalidFields);
        this.unsetRequiredFields.clear();
        for (const fieldName of unsetRequiredFields) {
            this.unsetRequiredFields.add(fieldName);
        }
    }

    markDirty() {
        this.dirty = true;
    }

    snapshot() {
        this.savePoint = createSavePoint(this);
    }

    /**
     * @returns {boolean}
     */
    restoreSnapshot() {
        const savePoint = this.savePoint;
        if (!savePoint) {
            return false;
        }
        this.changes = { ...savePoint.changes };
        this.textValues = markRaw({ ...savePoint.textValues });
        this.restoreValidity(savePoint);
        this.dirty = !this.isChangeSetEmpty || this.invalidFields.size > 0;
        this.savePoint = undefined;
        return true;
    }
}
