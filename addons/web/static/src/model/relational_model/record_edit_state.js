// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_edit_state */

import { markRaw } from "@odoo/owl";

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
}
