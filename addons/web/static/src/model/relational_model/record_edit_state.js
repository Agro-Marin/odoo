// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_edit_state - Owner object for a record's editable state (pending changes, dirty flag, validity, text-value tracking, savepoint) */

import { markRaw } from "@odoo/owl";

import { ChangeSet } from "./change_set.js";

/**
 * Owns the whole editable-state layer of a {@link RelationalRecord}: the
 * pending-edit {@link ChangeSet}, the reactive ``dirty`` signal, the
 * field-validity sets, the Char/Text/Html false-vs-"" tracking, and the
 * savepoint snapshot. Previously these lived as loose fields on the record,
 * mutated in-place by the ``relational_model/`` sibling helpers; consolidating
 * them here gives the ``(dirty, changes)`` invariant a single home
 * (``clearChanges`` is the only sanctioned reset and pairs the two atomically)
 * and lets the helpers talk to a cohesive object instead of poking privates.
 *
 * Reactivity contract (mirrors the pre-refactor record exactly):
 *   - This instance is stored on the record WITHOUT ``markRaw``, so — accessed
 *     through the record's reactive proxy — ``dirty`` and ``invalidFields``
 *     stay reactive (the UI binds to them). ``toRaw(record)._editState`` yields
 *     the raw owner, so the raw reads in ``record._update`` (which must not
 *     subscribe the dispatching field component) keep their raw semantics.
 *   - ``changeSet``'s bag, ``textValues`` and ``unsetRequiredFields`` are
 *     ``markRaw`` INSIDE this owner: the record's reactive surface is the
 *     merged ``data`` getter + ``dirty``/``invalidFields``, never these bags
 *     (a reactive change bag would re-render on every keystroke).
 */
export class RecordEditState {
    constructor() {
        // Non-reactive backing bag of pending field edits (see ChangeSet).
        this.changeSet = markRaw(new ChangeSet());

        // Reactive: UI bindings ("modified" indicator, Save/Discard gating).
        // NOT computed from the change set — ``dirty=true`` can coexist with an
        // empty change set during flow transitions (a provisional mark set by
        // ``record._update`` before async preprocessors land — Invariant 1; and
        // invalid input that never reaches the change bag — Invariant 2).
        this.dirty = false;

        // Reactive Set of fields that failed validation.
        /** @type {Set<string>} */
        this.invalidFields = new Set();
        // Non-reactive: required-but-unset bookkeeping (validation lifecycle).
        /** @type {Set<string>} */
        this.unsetRequiredFields = markRaw(new Set());
        this.closeInvalidFieldsNotification = () => {};

        // Non-reactive: server empty-string-vs-NULL tracking for char/text/html
        // fields, and the initial snapshot used by a no-savepoint discard.
        this.textValues = markRaw({});
        this.initialTextValues = {};

        // Savepoint snapshot (set by record_savepoint.addSavePoint); single-use.
        this.savePoint = undefined;
    }

    /**
     * The pending-edit bag, by reference — consumers iterate its keys, spread
     * it into ``data``, and set individual fields on it. Callers MUST NOT
     * replace it wholesale via this getter; use the setter (which goes through
     * {@link ChangeSet#replace}) so the ``markRaw`` invariant holds.
     *
     * @returns {Record<string, any>}
     */
    get changes() {
        return this.changeSet.raw;
    }

    set changes(initial) {
        this.changeSet.replace(initial);
    }

    /** True iff no field-level edits are pending. */
    get isChangeSetEmpty() {
        return this.changeSet.isEmpty;
    }

    /**
     * Atomically drop the pending edits AND lower the ``dirty`` signal. This is
     * the ONLY sanctioned way to empty the change bag: because the bag is
     * ``markRaw`` (non-reactive), clearing it without also resetting ``dirty``
     * would leave bindings showing "modified" until the next mutation. Invariant
     * I3 in ``STATE_MANAGEMENT.md``.
     */
    clearChanges() {
        this.changeSet.clear();
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
