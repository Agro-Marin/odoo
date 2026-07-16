// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/change_set - Value object that owns the markRaw bag of pending field edits on a record */

import { markRaw } from "@odoo/owl";

/**
 * Pending-edit accumulator for a single record. Owns the markRaw
 * ``_changes`` bag that {@link RelationalRecord} used to expose directly.
 * Contract rules from ``STATE_MANAGEMENT.md`` "Record State Architecture":
 *
 *   1. The bag is intentionally non-reactive (``markRaw``) — the record's
 *      reactive surface is the merged ``data`` getter + ``dirty`` flag, not
 *      this accumulator. A reactive bag would re-render on every keystroke.
 *
 *   2. ``dirty`` stays on the Record (read/written directly by
 *      ``form_compiler.js`` and ``stock_move_line_x2_many_field.js``); any
 *      bag reset must reset it atomically via ``Record._clearChanges()``,
 *      the only sanctioned reset entry point.
 *
 *   3. ``Object.keys``/``in`` must keep working on the bag — the save flow,
 *      ``_getChanges``, and ``_applyChanges`` undo logic rely on
 *      plain-object semantics, hence ``raw`` returns it directly.
 *
 * Does NOT own ``dirty`` (see rule 2), ``_textValues`` (Char/Text/Html
 * false-vs-"" flow), or ``_invalidFields``/``_unsetRequiredFields``
 * (validation lifecycle) — mixing those in would add coupling the
 * field-level edit flow doesn't need.
 *
 * NOTE (finding 13, deferred): this value object documents rather than
 * enforces its contract (helpers still mutate ``record._changes[f] = v`` on
 * the raw bag). The natural next refactor is to grow ``set``/``delete`` here
 * (or collapse ChangeSet into ``RecordEditState``) so the three-layer
 * indirection stops being ceremony without enforcement — out of scope for
 * this quality pass.
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
     * The underlying markRaw bag, returned by reference so existing
     * consumers that iterate keys, spread into ``data``, or call
     * ``_getChanges(this._changes, opts)`` keep working unchanged. Callers
     * MUST NOT replace it wholesale via this getter — use ``replace()`` /
     * ``clear()`` so the markRaw invariant is held.
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
