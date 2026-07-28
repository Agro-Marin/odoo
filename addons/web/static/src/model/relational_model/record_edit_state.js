// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_edit_state - Owner object for a record's editable state (pending changes, dirty flag, validity, text-value tracking, savepoint) */

import { markRaw } from "@odoo/owl";

/**
 * Owns the whole editable-state layer of a {@link RelationalRecord}: the
 * pending-edit bag, the reactive ``dirty`` signal, the field-validity sets, the
 * Char/Text/Html false-vs-"" tracking, and the savepoint snapshot. Previously
 * these lived as loose fields on the record, mutated in-place by the
 * ``relational_model/`` sibling helpers; consolidating them here gives the
 * ``(dirty, changes)`` invariant a single home (``clearChanges`` is the only
 * sanctioned reset and pairs the two atomically) and lets the helpers talk to a
 * cohesive object instead of poking privates.
 *
 * The bag used to live one level deeper, in a ``ChangeSet`` value object. That
 * object documented rather than enforced its contract — helpers still wrote
 * ``record._changes[f] = v`` straight through its ``raw`` getter — so the third
 * layer bought ceremony and no invariant. It has been folded in here, which is
 * the collapse its own docstring nominated. Direct keyed access stays public on
 * purpose: three code paths deliberately stage changes WITHOUT raising
 * ``dirty`` (the command engine's server-originated UPDATE, ``_multiSave``'s
 * fan-out, ``StaticList._addNewRecordAtIndex``'s sequence write), so a
 * ``set()`` that marked dirty would be wrong and one that didn't would add
 * nothing over plain assignment.
 *
 * Reactivity contract (mirrors the pre-refactor record exactly):
 *   - This instance is stored on the record WITHOUT ``markRaw``, so — accessed
 *     through the record's reactive proxy — ``dirty`` and ``invalidFields``
 *     stay reactive (the UI binds to them). ``toRaw(record)._editState`` yields
 *     the raw owner, so the raw reads in ``record._update`` (which must not
 *     subscribe the dispatching field component) keep their raw semantics.
 *   - The change bag, ``textValues`` and ``unsetRequiredFields`` are
 *     ``markRaw`` INSIDE this owner: the record's reactive surface is the
 *     merged ``data`` getter + ``dirty``/``invalidFields``, never these bags
 *     (a reactive change bag would re-render on every keystroke).
 */
export class RecordEditState {
    constructor() {
        /**
         * Pending edits keyed by field name. ``markRaw`` so OWL does NOT
         * deep-wrap the bag — see the reactivity contract above.
         *
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
     * The pending-edit bag, by reference — consumers iterate its keys, spread
     * it into ``data``, and set individual fields on it. Callers MUST NOT
     * replace it wholesale through this getter; assign to it instead, so the
     * ``markRaw`` invariant is re-applied.
     *
     * @returns {Record<string, any>}
     */
    get changes() {
        return this._changes;
    }

    /**
     * Replace the entire bag with a new set of pending edits. Used by the
     * ``_applyChanges`` undo path and the savepoint restore, which each capture
     * and later reinstall a snapshot.
     *
     * @param {Record<string, any>} initial
     */
    set changes(initial) {
        this._changes = markRaw(initial);
    }

    /** True iff no field-level edits are pending. */
    get isChangeSetEmpty() {
        return Object.keys(this._changes).length === 0;
    }

    /**
     * Atomically drop the pending edits AND lower the ``dirty`` signal. This is
     * the ONLY sanctioned way to empty the change bag: because the bag is
     * ``markRaw`` (non-reactive), clearing it without also resetting ``dirty``
     * would leave bindings showing "modified" until the next mutation. Invariant
     * I3 in ``STATE_MANAGEMENT.md``.
     */
    clearChanges() {
        this._changes = markRaw({});
        this.dirty = false;
    }

    /**
     * Raise the ``dirty`` signal without touching the change bag — for paths
     * that consider the record modified before (or without) a field-level edit
     * reaching the bag: ``record._update`` (Invariant 1) and ``setInvalidField``
     * (Invariant 2).
     */
    markDirty() {
        this.dirty = true;
    }
}
