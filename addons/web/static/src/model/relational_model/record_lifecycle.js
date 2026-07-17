// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_lifecycle - Archive, unarchive, delete, and duplicate operations extracted from RelationalRecord */

/**
 * Archive/unarchive, delete, and duplicate helpers, delegated the RelationalRecord
 * instance as first argument. Callers must invoke them inside
 * ``this.model.mutex.exec(() => helper(this))`` (Invariant I4) — the helpers
 * assume the mutex and do not re-enter it.
 */

import { markRaw } from "@odoo/owl";
import { modelLog } from "@web/core/utils/asset_log";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Archive via ``action_archive``. The server may return an action descriptor
 * (e.g. a confirm dialog for linked records); ``hooks.ui.onDisplayArchiveAction``
 * decides whether to show it — the default hook bypasses it and reloads.
 *
 * @param {RelationalRecord} record
 * @param {() => Promise<any>} [reload] Override for the post-archive reload.
 *  Defaults to a single-datapoint ``record._load()`` (correct for a form).
 *  Multi-record views (kanban) must pass a list-level reload so the archived
 *  record is actually removed from its group and the counters/progressbars
 *  refresh — a single-datapoint reload re-reads the record by id (which
 *  ignores the active filter) and leaves a stale card behind.
 * @returns {Promise<any>} archive hook result (usually a reload promise)
 */
export async function archive(record, reload) {
    modelLog("archive", record.resModel, record.resId);
    return toggleArchive(record, true, reload);
}

/**
 * Unarchive the record via the ``action_unarchive`` ORM method.
 * See {@link archive} for hook and mutex contract.
 *
 * @param {RelationalRecord} record
 * @param {() => Promise<any>} [reload] See {@link archive}.
 * @returns {Promise<any>}
 */
export async function unarchive(record, reload) {
    modelLog("unarchive", record.resModel, record.resId);
    return toggleArchive(record, false, reload);
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
async function toggleArchive(record, state, reload = () => record._load()) {
    const method = state ? "action_archive" : "action_unarchive";
    const action = await record.model.orm.call(
        record.resModel,
        method,
        [[record.resId]],
        {
            context: record.context,
        },
    );
    return record.model.hooks.ui.onDisplayArchiveAction(action, reload);
}

/**
 * Unlink the record from the server and update the local resIds list.
 *
 * - If ``orm.unlink`` returns falsy (server-side veto), returns ``false``
 *   without mutating local state.
 * - If the deleted record wasn't the last in ``resIds``, navigates to the
 *   next record (same index, or last if we were at the end).
 * - If it was the last, resets local state in place (``_values`` to
 *   defaults, clears ``_textValues``/``_changes``, rebuilds ``data``,
 *   re-derives eval context); record stays mounted with ``resId === false``
 *   until the caller navigates away.
 *
 * Named ``deleteRecord`` since ``delete`` is a reserved word.
 *
 * @param {RelationalRecord} record
 * @returns {Promise<boolean | undefined>} ``false`` if vetoed, otherwise
 *  ``undefined`` after deletion + state reset/nav
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
 * Duplicate the record via ``copy`` and navigate to the new record in edit mode.
 *
 * The new resId is inserted into ``resIds`` right after the source record's
 * position, so pager navigation from the duplicate leads back to the original.
 * ``load`` triggers a full reload so server-side ``copy`` overrides (e.g.
 * sequence regeneration, defaults) are visible.
 *
 * Named ``duplicateRecord`` for naming consistency with {@link deleteRecord}.
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
