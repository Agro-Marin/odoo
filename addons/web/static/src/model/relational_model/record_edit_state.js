// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_edit_state */

import { markRaw } from "@odoo/owl";

/**
 * @typedef {{
 *  changes: Record<string, any>,
 *  textValues: Record<string, any>,
 *  invalidFields: string[],
 *  unsetRequiredFields: string[],
 * }} SavePoint
 */

/**
 * The savepoint shape, in one place. Built here rather than by the caller so
 * the fields a savepoint carries cannot drift from the fields
 * {@link RecordEditState#restoreSnapshot} puts back — adding one to the
 * snapshot without restoring it is a silent half-restore.
 *
 * @param {{
 *  changes?: Record<string, any>,
 *  textValues?: Record<string, any>,
 *  invalidFields?: Iterable<string>,
 *  unsetRequiredFields?: Iterable<string>,
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

        /** @type {Set<string>} */
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
     * `dirty` tracks user edits, but `_applyChanges` (onchange echoes, applied
     * x2many UPDATE commands, default values) fills the change set without
     * raising it. Both halves are sent on save, so anything asking "is there
     * something pending here?" must read this, not `dirty`.
     *
     * @returns {boolean}
     */
    get hasPendingChanges() {
        return this.dirty || !this.isChangeSetEmpty;
    }

    clearChanges() {
        this._changes = markRaw({});
        this.dirty = false;
    }

    /** The pending edits became the new baseline. */
    commit() {
        this.clearChanges();
        this.initialTextValues = markRaw({ ...this.textValues });
    }

    /** The pending edits are dropped; the baseline is what remains. */
    rollback() {
        this.clearChanges();
        this.textValues = markRaw({ ...this.initialTextValues });
    }

    /** No baseline at all: a record that no longer has server values. */
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

    /**
     * Park the whole pending-edit set so a sub-flow that gets cancelled — a
     * sub-form dialog over an x2many child, an extended-field reload — can put
     * it back. Every piece lives on this object, so the snapshot is taken here
     * rather than reassembled by a caller reaching through the record.
     */
    snapshot() {
        this.savePoint = createSavePoint(this);
    }

    /**
     * @returns {boolean} false when there was nothing parked, so a caller can
     *  tell "restored the snapshot" from "fell back to the server values"
     */
    restoreSnapshot() {
        const savePoint = this.savePoint;
        if (!savePoint) {
            return false;
        }
        this.changes = { ...savePoint.changes };
        this.textValues = markRaw({ ...savePoint.textValues });
        this.restoreValidity(savePoint);
        // Derived, not snapshotted: a record whose only pending state is an
        // INVALID field has an empty change set and must still read dirty, or
        // the edit is dropped without a prompt.
        this.dirty = !this.isChangeSetEmpty || this.invalidFields.size > 0;
        this.savePoint = undefined;
        return true;
    }
}
