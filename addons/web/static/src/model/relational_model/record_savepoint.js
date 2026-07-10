// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_savepoint - Savepoint snapshot/restore and discard logic extracted from RelationalRecord */

/**
 * Savepoint + discard logic: capture/restore a record's editable state across
 * sub-flows that may be discarded, and run the full discard sequence (restore
 * from savepoint, or clear to server truth if none exists). Delegation
 * pattern — helpers take the RelationalRecord as first argument, mirroring
 * record_save.js.
 *
 * Snapshot carriers (captured by {@link addSavePoint}): ``_changes``
 * (committed edits), ``_invalidFields`` (invalid input that never reached
 * ``_changes``), ``_textValues`` (server empty-string-vs-NULL tracking).
 *
 * ``dirty`` is derived at restore time from ``_changes``/``_invalidFields``
 * rather than stored — storing it separately caused a "ghost dirty" bug
 * where ``dirty=true`` survived a restore even after the invalid input that
 * caused it was gone (see ``record_savepoint.test.js``).
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
 * Caller must ensure ``record._savePoint`` is set.
 *
 * Resets ``_changes``/``_textValues``/``_invalidFields`` to the snapshot and
 * derives ``dirty`` from them; consumes ``_savePoint`` (single-use).
 *
 * Does not rebuild ``record.data`` (caller does, from ``_values + _changes``),
 * recurse into x2many children (parent ``_discard`` handles that), or run
 * ``_checkValidity()`` (caller does, after rebuild).
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
 * With a savepoint present, restores it via {@link restoreFromSavePoint}
 * (``_changes``/``_textValues``/``_invalidFields`` revert to the snapshot;
 * pre-savepoint invalid-input flags survive). Without one, clears
 * ``_changes`` via ``record._clearChanges()`` (Invariant I3 — atomically
 * pairs ``_changes={}`` with ``dirty=false``), resets
 * ``_textValues`` to the initial server snapshot, and wipes
 * ``_invalidFields`` (data is back to server truth, so stale invalid flags
 * are dropped).
 *
 * Both paths then rebuild ``data`` from ``_values + _changes``, refresh the
 * eval context, and (for existing records) re-run ``_checkValidity`` to
 * recompute unset-required fields — it never touches invalid-input flags it
 * doesn't own, so the savepoint branch's restored flags survive.
 *
 * Recurses into x2many child lists via ``record._changes[fieldName]._discard()``
 * before branching, so children's post-discard state is visible to the
 * parent's data rebuild. Also closes any open invalid-fields notification and
 * reverts active-field mutations from the discarded sub-flow.
 *
 * Must run under ``record.model.mutex`` (Invariant I4).
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
        // See restoreFromSavePoint above for invariants.
        restoreFromSavePoint(record);
    } else {
        record._clearChanges();
        record._textValues = markRaw({ ...record._initialTextValues });
    }
    record.data = { ...record._values, ...record._changes };
    record._setEvalContext();
    if (!fromSavePoint) {
        // Data is back to server truth, so prior invalid flags are stale.
        record._invalidFields.clear();
    }
    if (!record.isNew) {
        // Recompute unset-required fields; never touches invalid-input
        // flags it doesn't own.
        record._checkValidity();
    }
    record._closeInvalidFieldsNotification();
    record._closeInvalidFieldsNotification = () => {};
    record._restoreActiveFields();
}
