// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/change_set - Value object that owns the markRaw bag of pending field edits on a record */

import { markRaw } from "@odoo/owl";

/**
 * Pending-edit accumulator for a single record.
 *
 * Owns the markRaw ``_changes`` object that {@link RelationalRecord}
 * exposed directly as a public field before this extraction.  Codifies
 * the three contract rules the field-level invariants from
 * ``STATE_MANAGEMENT.md`` "Record State Architecture" demanded:
 *
 *   1. The change bag is **intentionally non-reactive** (``markRaw``).
 *      The record's reactive surface is the merged ``data`` getter +
 *      ``dirty`` flag, not the raw change accumulator. Mutations to a
 *      reactive bag would re-render the world on every keystroke.
 *
 *   2. Whenever the bag is reset, the record's reactive ``dirty`` flag
 *      MUST be reset on the same atomic step. This collaborator does
 *      NOT own ``dirty`` — the Record retains it as its public reactive
 *      field (consumers like ``form_compiler.js`` and
 *      ``stock_move_line_x2_many_field.js`` read/write ``record.dirty``
 *      directly). The atomicity is enforced by the paired
 *      ``Record._clearChanges()`` helper, which is the only sanctioned
 *      bag-reset entry point.
 *
 *   3. ``Object.keys`` enumeration and ``key in changes`` membership
 *      checks must keep working against the underlying object — the
 *      save flow, the ``_getChanges`` filter, and ``_applyChanges``
 *      undo logic all rely on plain-object semantics. The ``raw``
 *      getter returns the bag directly so existing call sites that
 *      walk ``record._changes`` via the Record's getter keep working
 *      unchanged.
 *
 * What this class does NOT own:
 *   - ``dirty`` (Record's public reactive field — see invariant 2)
 *   - ``_textValues`` (separate Char/Text/Html flow for distinguishing
 *     ``false`` from ``""`` in the eval context)
 *   - ``_invalidFields`` / ``_unsetRequiredFields`` (validation lifecycle)
 *
 * Mixing those into ChangeSet would add coupling the field-level edit
 * flow does not need.
 */
export class ChangeSet {
    constructor() {
        /**
         * Pending edits keyed by field name. ``markRaw`` so OWL does NOT
         * deep-wrap the bag — see invariant 1 above.
         *
         * @type {Record<string, any>}
         */
        this._changes = markRaw({});
    }

    /**
     * Drop the entire change bag. Pair with ``record.dirty = false`` via
     * ``Record._clearChanges()``; do not call this directly from outside
     * the Record class.
     */
    clear() {
        this._changes = markRaw({});
    }

    /**
     * Replace the entire bag with a new initial set of pending edits.
     * Used by the ``_applyChanges`` undo path which captures and restores
     * a snapshot of pre-change state.
     *
     * @param {Record<string, any>} initial
     */
    replace(initial) {
        this._changes = markRaw(initial);
    }

    /**
     * Single-field assignment — used by ``_applyChanges`` to land each
     * incoming edit into the bag.
     *
     * @param {string} key
     * @param {any} value
     */
    setField(key, value) {
        this._changes[key] = value;
    }

    /**
     * Drop a single pending edit — used by the ``_update`` many2one
     * same-value guard that detects a "selected the same partner again"
     * non-change and removes the no-op edit so the dirty signal stays
     * accurate.
     *
     * @param {string} key
     */
    delete(key) {
        delete this._changes[key];
    }

    /**
     * @param {string} key
     * @returns {boolean}
     */
    has(key) {
        return key in this._changes;
    }

    /**
     * The underlying markRaw bag. Returned by reference so existing
     * consumers that iterate keys, spread into ``data``, or call
     * ``_getChanges(this._changes, opts)`` keep working unchanged.
     *
     * Callers MUST NOT replace the bag wholesale via this getter —
     * use ``replace()`` / ``clear()`` so the markRaw invariant is held.
     *
     * @returns {Record<string, any>}
     */
    get raw() {
        return this._changes;
    }

    /** True iff no field-level edits are pending. */
    get isEmpty() {
        return Object.keys(this._changes).length === 0;
    }
}
