// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_savepoint - Savepoint snapshot/restore and discard logic extracted from RelationalRecord */

/**
 * Savepoint + discard logic: capture and restore a record's editable
 * state across sub-flows that may be discarded; perform the full discard
 * sequence that picks between the savepoint-restore path and the clear-
 * to-server-truth path based on whether ``record._savePoint`` is set.
 *
 * All three helpers receive the RelationalRecord instance as first
 * argument (delegation pattern, mirrors record_save.js).
 *
 * Snapshot carriers (state captured by {@link addSavePoint}):
 *
 *   - ``_changes``       — committed field edits (Invariant 1 source).
 *   - ``_invalidFields`` — fields with invalid user input that never
 *                          reached ``_changes`` (Invariant 2 source).
 *   - ``_textValues``    — server-side empty-string-vs-NULL tracking for
 *                          char/text/html fields.
 *
 * ``dirty`` is NOT stored independently — it is derived at restore time
 * from ``_changes`` and ``_invalidFields``.  Storing it explicitly used
 * to be load-bearing for Invariant 2 (when ``_invalidFields`` was wiped
 * by the post-restore ``_invalidFields.clear()`` in ``_discard``); now
 * that ``_invalidFields`` travels with the snapshot, the field is
 * provably redundant.  Removing it also fixes the "ghost dirty" bug
 * (``record_savepoint.test.js`` describes the trace) where the previous
 * implementation preserved ``dirty=true`` after restore even when the
 * Invariant-2 invalid input that originally caused it was lost.
 */

import { markRaw } from "@odoo/owl";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Take a snapshot of the record's editable state into ``record._savePoint``.
 *
 * Recurses into nested ``StaticList`` instances on x2many fields so a
 * sub-form opened on a child record can later restore the parent's view
 * of the list independently.
 *
 * @param {RelationalRecord} record
 */
export function addSavePoint(record) {
    record._savePoint = markRaw({
        textValues: { ...record._textValues },
        changes: { ...record._changes },
        invalidFields: [...record._invalidFields],
    });
    for (const fieldName of Object.keys(record._changes)) {
        if (["one2many", "many2many"].includes(record.fields[fieldName].type)) {
            record._changes[fieldName]._addSavePoint();
        }
    }
}

/**
 * Restore ``record`` to the state captured by a prior ``addSavePoint``.
 *
 * Caller is responsible for invoking this only when ``record._savePoint``
 * is set (mirror of the pre-extraction guard in ``record._discard``).
 *
 * Side effects:
 *   - ``_changes``, ``_textValues``, ``_invalidFields`` reset to snapshot.
 *   - ``dirty`` derived from the restored ``_changes`` and ``_invalidFields``.
 *   - ``_savePoint`` consumed (set to undefined) — savepoints are
 *     single-use.
 *
 * Does NOT:
 *   - Rebuild ``record.data`` (caller does this from ``_values + _changes``).
 *   - Recurse into x2many children (parent ``_discard`` handles that
 *     via the ``Object.keys(_changes).forEach(...)._discard()`` loop).
 *   - Run ``_checkValidity()`` (caller does this after rebuild).
 *
 * @param {RelationalRecord} record
 */
export function restoreFromSavePoint(record) {
    const savePoint = record._savePoint;
    record._changes = markRaw({ ...savePoint.changes });
    record._textValues = markRaw({ ...savePoint.textValues });
    record._invalidFields = new Set(savePoint.invalidFields);
    record.dirty =
        Object.keys(record._changes).length > 0 || record._invalidFields.size > 0;
    record._savePoint = undefined;
}

/**
 * Discard the record's pending edits.
 *
 * Branching:
 *   - **Savepoint present** (``record._savePoint`` truthy): restore the
 *     captured snapshot via {@link restoreFromSavePoint}. ``_changes``,
 *     ``_textValues``, ``_invalidFields`` revert to the snapshot;
 *     ``dirty`` is derived from the restored state. Invalid-input flags
 *     captured before the savepoint survive the discard.
 *   - **No savepoint**: clear ``_changes`` via ``record._clearChanges()``
 *     (Invariant I3 — atomically pairs ``_changes={}`` with
 *     ``dirty=false``). Reset ``_textValues`` to the initial server snapshot.
 *     Wipe ``_invalidFields`` entirely (data is back to ``_values`` —
 *     server truth — so any prior invalid-input flag is by construction stale).
 *
 * After the branch, both paths rebuild ``data`` from the merged
 * ``_values + _changes``, refresh the eval context, and (when the record
 * is not a new draft) re-run validity to recompute the unset-required
 * subset against the now-current data. Invariant: ``_checkValidity``
 * never touches invalid-input flags it doesn't own, so the savepoint
 * branch keeps the restored Invariant-2 flags intact.
 *
 * Recurses into x2many child lists via
 * ``record._changes[fieldName]._discard()`` BEFORE branching — the
 * child's own discard logic runs first so its post-discard state is
 * visible to the parent's data rebuild.
 *
 * Side-effects on supporting state:
 *   - Closes the invalid-fields notification (if open) and resets the
 *     closer to a no-op.
 *   - Calls ``record._restoreActiveFields()`` to revert any active-field
 *     mutations performed during the discarded sub-flow.
 *
 * Must run under ``record.model.mutex`` (Invariant I4 — caller in
 * record.js wraps via ``mutex.exec(() => discard(this))``).
 *
 * @param {RelationalRecord} record
 */
export function discard(record) {
    for (const fieldName of Object.keys(record._changes)) {
        if (["one2many", "many2many"].includes(record.fields[fieldName].type)) {
            record._changes[fieldName]._discard();
        }
    }
    const fromSavePoint = !!record._savePoint;
    if (fromSavePoint) {
        // Restore ``_changes``, ``_textValues``, ``_invalidFields``
        // and derive ``dirty`` from the restored state.  See
        // ``restoreFromSavePoint`` above for invariants.
        restoreFromSavePoint(record);
    } else {
        record._clearChanges();
        record._textValues = markRaw({ ...record._initialTextValues });
    }
    record.data = { ...record._values, ...record._changes };
    record._setEvalContext();
    if (!fromSavePoint) {
        // No-savepoint path: data is back to ``_values`` (server
        // truth), so any prior invalid-input flags are stale by
        // construction — wipe and re-derive.
        record._invalidFields.clear();
    }
    if (!record.isNew) {
        // Re-check unset-required fields against the (possibly new)
        // arch and current data.  In the savepoint branch this
        // refreshes the unset-required subset on top of the
        // restored invalid-input flags; ``_checkValidity`` only
        // adds/removes its own ``_unsetRequiredFields`` category
        // and never wipes invalid-input entries it doesn't own.
        record._checkValidity();
    }
    record._closeInvalidFieldsNotification();
    record._closeInvalidFieldsNotification = () => {};
    record._restoreActiveFields();
}
