// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_lifecycle - Archive, unarchive, delete, and duplicate operations extracted from RelationalRecord */

/**
 * Record lifecycle operations: archive/unarchive (via action_archive /
 * action_unarchive ORM methods), delete (unlink + resIds bookkeeping +
 * post-delete state reset), and duplicate (copy + resIds bookkeeping +
 * navigate to the new record in edit mode).
 *
 * All four helpers receive the RelationalRecord instance as the first
 * argument (delegation pattern). The mutex serialization contract
 * (Invariant I4) is preserved at the call site in record.js: every
 * class method that wraps these helpers calls them inside
 * ``this.model.mutex.exec(() => helper(this))``. The helpers themselves
 * assume they run under the mutex and do not re-enter it.
 */

import { markRaw } from "@odoo/owl";
import { modelLog } from "@web/core/utils/asset_log";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Archive the record via the ``action_archive`` ORM method.
 *
 * The server may return an action descriptor (e.g. a confirmation
 * dialog asking the user to archive linked records); the
 * ``hooks.ui.onDisplayArchiveAction`` hook decides whether to display
 * it. The default hook bypasses the dialog and reloads the record.
 *
 * Must run under ``record.model.mutex`` (caller's responsibility — see
 * Invariant I4 in
 * ``workspaces/workspace-LMMG/brainstorms/2026-05-23-web-model-layer-decomposition.md``).
 *
 * @param {RelationalRecord} record
 * @returns {Promise<any>} the result of the archive hook (typically a
 *  reload promise, but third-party hooks may return an action result)
 */
export async function archive(record) {
    modelLog("archive", record.resModel, record.resId);
    return toggleArchive(record, true);
}

/**
 * Unarchive the record via the ``action_unarchive`` ORM method.
 * See {@link archive} for hook and mutex contract.
 *
 * @param {RelationalRecord} record
 * @returns {Promise<any>}
 */
export async function unarchive(record) {
    modelLog("unarchive", record.resModel, record.resId);
    return toggleArchive(record, false);
}

/**
 * Internal: dispatch to ``action_archive`` or ``action_unarchive`` based
 * on the ``state`` boolean. Not exported because outside callers should
 * use the directional {@link archive} / {@link unarchive} entry points.
 *
 * @param {RelationalRecord} record
 * @param {boolean} state ``true`` to archive, ``false`` to unarchive
 * @returns {Promise<any>}
 */
async function toggleArchive(record, state) {
    const method = state ? "action_archive" : "action_unarchive";
    const action = await record.model.orm.call(
        record.resModel,
        method,
        [[record.resId]],
        {
            context: record.context,
        },
    );
    const reload = () => record._load();
    return record.model.hooks.ui.onDisplayArchiveAction(action, reload);
}

/**
 * Unlink the record from the server and update the local resIds list.
 *
 * Behavior:
 * - If ``orm.unlink`` returns falsy (e.g. server-side veto), returns
 *   ``false`` without mutating local state.
 * - If the deleted record was not the last in ``resIds``, navigates to
 *   the next record (same index, or last if we were at the end).
 * - If it was the last, clears local state in place: resets ``_values``
 *   to defaults, clears ``_textValues`` and ``_changes``, rebuilds
 *   ``data``, and re-derives eval context. The record stays mounted
 *   with ``resId === false`` until the caller navigates away.
 *
 * Exported as ``deleteRecord`` because ``delete`` is a JavaScript
 * reserved word and cannot be used as a function name in ES modules.
 *
 * Must run under ``record.model.mutex`` (Invariant I4).
 *
 * @param {RelationalRecord} record
 * @returns {Promise<boolean | undefined>} ``false`` if unlink was vetoed,
 *  otherwise ``undefined`` after successful deletion + state reset / nav
 */
export async function deleteRecord(record) {
    modelLog("delete", record.resModel, record.resId);
    const unlinked = await record.model.orm.unlink(record.resModel, [record.resId], {
        context: record.context,
    });
    if (!unlinked) {
        return false;
    }
    const resIds = record.resIds.slice();
    const index = resIds.indexOf(/** @type {number} */ (record.resId));
    // resId may be absent from resIds (standalone Record with caller-supplied
    // ids, config drift): splice(-1, 1) would silently drop the LAST pager id
    // and resIds[min(-1, n)] would blank the form despite remaining records.
    if (index >= 0) {
        resIds.splice(index, 1);
    }
    const resId = resIds[Math.min(Math.max(index, 0), resIds.length - 1)] || false;
    if (resId) {
        await record.model.load({ resId, resIds });
    } else {
        record.model._patchConfig(record.config, { resId: false });
        record._values = markRaw(record._parseServerValues(record._getDefaultValues()));
        record._textValues = markRaw({});
        record._clearChanges();
        record.data = { ...record._values };
        record._setEvalContext();
    }
}

/**
 * Duplicate the record via the ``copy`` ORM method and navigate to the
 * new record in edit mode.
 *
 * The new resId is inserted into ``resIds`` immediately after the
 * source record's position, so pager navigation from the duplicate
 * leads back to the original. The model's ``load`` triggers a full
 * reload of the duplicate so server-side ``copy`` overrides (e.g.
 * sequence regeneration, default fields) are visible.
 *
 * Exported as ``duplicateRecord`` for symmetry with
 * {@link deleteRecord} (the verb collision rationale in the plan
 * applies primarily to ``delete``; ``duplicate`` follows the same
 * naming for import-site consistency).
 *
 * Must run under ``record.model.mutex`` (Invariant I4).
 *
 * @param {RelationalRecord} record
 * @returns {Promise<void>}
 */
export async function duplicateRecord(record) {
    modelLog("duplicate", record.resModel, record.resId);
    const kwargs = { context: record.context };
    const index = record.resIds.indexOf(/** @type {number} */ (record.resId));
    const [resId] = await record.model.orm.call(
        record.resModel,
        "copy",
        [[record.resId]],
        kwargs,
    );
    const resIds = record.resIds.slice();
    resIds.splice(index + 1, 0, resId);
    await record.model.load({ resId, resIds, mode: "edit" });
}
