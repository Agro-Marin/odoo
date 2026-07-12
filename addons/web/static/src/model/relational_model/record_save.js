// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_save - Save logic extracted from RelationalRecord */

/**
 * Record persistence logic: web_save RPC, sendBeacon for urgent saves,
 * creation flow, reload, and error handling.
 * Receives the RelationalRecord instance as first argument (delegation pattern).
 */

import { markRaw, markup } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { RequestEntityTooLargeError } from "@web/core/network/rpc";
import { modelLog } from "@web/core/utils/asset_log";

import { buildConcurrencyBaseline } from "./concurrency_baseline.js";
import { FetchRecordError } from "./errors.js";
import { getBasicEvalContext } from "./field_context.js";
import { getFieldsSpec } from "./field_spec.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Collect the pending floating-commands promises (``_commandsPromise``, see
 * ``StaticList._trackCommandsPromise``) of every x2many list reachable from
 * ``record``, including lists held by cached sub-records.
 *
 * @param {RelationalRecord} record
 * @param {Promise<void>[]} proms
 * @param {Set<any>} seen
 */
function collectPendingCommandsPromises(record, proms, seen) {
    for (const fieldName of Object.keys(record.activeFields)) {
        const field = record.fields[fieldName];
        if (!field || !["one2many", "many2many"].includes(field.type)) {
            continue;
        }
        const list = record.data[fieldName];
        if (!list || seen.has(list)) {
            continue;
        }
        seen.add(list);
        if (list._commandsPromise) {
            proms.push(list._commandsPromise);
        }
        for (const subRecord of Object.values(list._cache)) {
            if (!seen.has(subRecord)) {
                seen.add(subRecord);
                collectPendingCommandsPromises(subRecord, proms, seen);
            }
        }
    }
}

/**
 * Barrier: wait until every x2many list reachable from ``record`` has
 * finished applying floating commands. Command application can be async
 * (``applyCommands`` fetches the values of linked/page-fill records); its
 * callers in sync chains (``_setData`` → ``parseServerValues``) cannot await
 * it, so a save started right after could serialize commands from — and,
 * worse, have its post-save state clean-up (``_clearCommands``/``_setData``)
 * raced by — a load that is still in flight. Sequencing the save after the
 * pending work removes that race.
 *
 * A settling load can replay deferred commands that trigger a further fetch
 * (tracked on the list again), so re-collect until quiescent — capped: a
 * pathological replay chain (e.g. a server that keeps returning fewer rows
 * than requested) must degrade into a best-effort save with a warning, not
 * hang silently inside the mutex and wedge every later model operation.
 * The tracked promises never reject (rejections are surfaced separately,
 * see ``StaticList._trackCommandsPromise``).
 *
 * @param {RelationalRecord} record
 */
const PENDING_COMMANDS_MAX_ITERATIONS = 100;
async function waitForPendingCommands(record) {
    for (let i = 0; i < PENDING_COMMANDS_MAX_ITERATIONS; i++) {
        /** @type {Promise<void>[]} */
        const proms = [];
        collectPendingCommandsPromises(record, proms, new Set());
        if (!proms.length) {
            return;
        }
        await Promise.all(proms);
    }
    console.warn(
        `record_save: x2many command replay did not quiesce after ` +
            `${PENDING_COMMANDS_MAX_ITERATIONS} barrier iterations ` +
            `(resModel: ${record.resModel}); proceeding with a best-effort save`,
    );
}

/**
 * Persist a record via web_save. Handles creation, sendBeacon for urgent saves,
 * field spec computation, and post-save reload.
 * @param {RelationalRecord} record
 * @param {{ reload?: boolean, onError?: (e: Error, actions: { discard: () => void, retry: () => any }) => any, nextId?: number }} [options]
 * @returns {Promise<boolean>}
 */
export async function save(record, { reload = true, onError, nextId } = {}) {
    modelLog("save", record.resModel, record.resId || "(new)");
    if (record.model._closeUrgentSaveNotification) {
        record.model._closeUrgentSaveNotification();
    }
    const creation = !record.resId;
    if (nextId) {
        if (creation) {
            throw new Error("Cannot set nextId on a new record");
        }
        reload = true;
    }
    if (!record.model.urgentSave.isActive) {
        // Not on the urgent (tab-close) path: that one must reach sendBeacon
        // without awaiting, and serializeCommands has a deferred-commands
        // fallback that keeps the payload correct on a best-effort basis.
        await waitForPendingCommands(record);
    }
    // before saving, abandon new invalid, untouched records in x2manys
    for (const fieldName of Object.keys(record.activeFields)) {
        const field = record.fields[fieldName];
        if (
            ["one2many", "many2many"].includes(field.type) &&
            !field.relatedPropertyField
        ) {
            record.data[fieldName]._abandonRecords();
        }
    }
    if (!record._checkValidity({ displayNotification: true })) {
        return false;
    }
    const changes = record._getChanges();
    delete changes.id; // id never changes, and should not be written
    // Field-scoped optimistic locking: capture the originally-loaded (baseline)
    // value of each field being written, so the server rejects only a genuine
    // per-field conflict and ignores concurrent writes to OTHER fields (e.g.
    // background stored-compute recomputations). The exclusion rules live in
    // one shared helper (also used by the list mass-edit path) so the two can't
    // drift; the server skips any field it has no baseline for (fails open).
    const concurrencyBaseline = buildConcurrencyBaseline(record, Object.keys(changes));
    if (!creation && !Object.keys(changes).length) {
        if (nextId) {
            // No changes — caller wants to navigate to ``nextId``. Run the
            // load to completion before returning so the save-flow's
            // ``Promise<boolean>`` contract holds (the load result is
            // ``Promise<void>`` which TS can't fold into ``boolean``).
            await record.model.load({ resId: nextId });
            return true;
        }
        record._clearChanges();
        record.data = { ...record._values };
        // ``_changes`` may have held entries that serialize to nothing
        // (readonly-field edits, x2many lists without commands): ``data`` is
        // visibly reverted above, so the eval contexts must follow — or
        // modifier expressions keep evaluating against the discarded values
        // (compare record_savepoint.discard, which always re-runs it).
        record._setEvalContext();
        return true;
    }
    if (
        record.model.urgentSave.isActive &&
        record.model.useSendBeaconToSaveUrgently &&
        !record.model.env.inDialog &&
        record.resId // sendBeacon cannot return the new ID for creation
    ) {
        // The page is closing: a classic RPC can be cancelled (payload too
        // heavy, network too slow, tab closing too fast), so use sendBeacon
        // instead — not cancellable, but payload-limited (~64k). If it fails,
        // block the unload instead so the user's work isn't lost.
        const route = `/web/dataset/call_kw/${record.resModel}/web_save`;
        // Field-scoped optimistic locking: mirror the normal-save path so the
        // server can reject a genuine concurrent edit even when the save was
        // initiated by sendBeacon on tab close. This branch only runs for an
        // existing record (resId truthy), so the baseline is meaningful; an
        // empty baseline (e.g. only x2many changed) simply skips the check —
        // the right call on tab close, where we must never drop the user's work.
        const urgentKwargs = {
            context: record.context,
            specification: {},
            known_values: concurrencyBaseline,
        };
        const params = {
            model: record.resModel,
            method: "web_save",
            args: [record.resId ? [record.resId] : [], changes],
            kwargs: urgentKwargs,
        };
        const data = { jsonrpc: "2.0", method: "call", params };
        const blob = new Blob([JSON.stringify(data)], {
            type: "application/json",
        });
        const succeeded = navigator.sendBeacon(route, blob);
        if (succeeded) {
            record._values = markRaw({ ...record._values, ...record._changes });
            // Mirror the reload:false branch: clear each x2many list's staged
            // CREATE/LINK/UPDATE commands now that the beacon persisted them.
            // Without this, if the page survives (e.g. bfcache Back after the
            // tab-close beacon), the stale commands remain on the lists and the
            // next save re-serializes them, creating duplicate child rows. Must
            // run before ``_clearChanges()`` empties ``_changes``.
            for (const fieldName of Object.keys(record.activeFields)) {
                const field = record.fields[fieldName];
                if (
                    ["one2many", "many2many"].includes(field.type) &&
                    !field.relatedPropertyField
                ) {
                    record._changes[fieldName]?._clearCommands();
                }
            }
            record._clearChanges();
            // Mirror the reload:false branch below: rebuild ``data`` from the
            // just-persisted ``_values`` and re-run the eval context / text-value
            // baselines. Without this, a page that SURVIVES the beacon (bfcache
            // Back after the tab-close beacon) keeps ``data`` merged from the now
            // discarded ``_changes`` and modifier expressions / a later Discard
            // evaluate against stale pre-save values.
            record.data = { ...record._values };
            record._setEvalContext();
            record._initialTextValues = { ...record._textValues };
        } else {
            record.model._closeUrgentSaveNotification =
                record.model.hooks.ui.onDisplayUrgentSave(
                    _t(
                        `Heads up! Your recent changes are too large to save automatically. Please click the %(upload_icon)s button now to ensure your work is saved before you exit this tab.`,
                        {
                            upload_icon: markup`<i class="fa-solid fa-cloud-arrow-up"></i>`,
                        },
                    ),
                );
        }
        return succeeded;
    }
    /** @type {Record<string, any>[]} */
    let records;
    // In-flight marker for urgentSave(): held from the FIRST await after the
    // `changes` snapshot (the onWillSaveRecord hook — enterprise controllers
    // park saves there for seconds behind dialogs/RPCs) until the change bag
    // is cleared, so a tab close anywhere in that window skips the beacon
    // instead of re-sending the same (non-idempotent) x2many commands: the
    // beacon plus the parked webSave used to double-write duplicate child
    // rows. Awaits BEFORE the snapshot need no marker — a beacon firing
    // there clears `_changes`, so the snapshot comes out empty.
    record._saveInFlight = true;
    try {
        const canProceed = await record.model.hooks.lifecycle.onWillSaveRecord(
            record,
            changes,
        );
        if (canProceed === false) {
            return false;
        }
        // keep x2many orderBy if we stay on the same record
        /** @type {Record<string, any>} */
        const orderBys = {};
        if (!nextId) {
            for (const fieldName of record.fieldNames) {
                if (["one2many", "many2many"].includes(record.fields[fieldName].type)) {
                    orderBys[fieldName] = record.data[fieldName].orderBy;
                }
            }
        }
        let fieldSpec = {};
        if (reload) {
            fieldSpec = getFieldsSpec(
                record.activeFields,
                record.fields,
                getBasicEvalContext(record.config),
                { orderBys },
            );
        }
        const kwargs = {
            context: record.context,
            specification: fieldSpec,
            next_id: nextId,
        };
        // Field-scoped optimistic locking: send the baseline values of the
        // fields being written so the server rejects only genuine per-field
        // conflicts and ignores concurrent writes to other fields. (Empty
        // baseline => no check.)
        if (record.resId) {
            kwargs.known_values = concurrencyBaseline;
        }
        try {
            records = await record.model.orm.webSave(
                record.resModel,
                record.resId ? [record.resId] : [],
                changes,
                kwargs,
            );
        } catch (e) {
            if (onError && !(e instanceof RequestEntityTooLargeError)) {
                return onError(e, {
                    discard: () => record._discard(),
                    retry: () => save(record, { reload, onError, nextId }),
                });
            }
            if (!record.isInEdition) {
                await record._load({});
            }
            throw e;
        }
        if (reload && !records.length) {
            throw new FetchRecordError([
                /** @type {number} */ (nextId || record.resId),
            ]);
        }
        if (creation) {
            const resId = records[0].id;
            const resIds = [...record.resIds, resId];
            record.model._patchConfig(record.config, { resId, resIds });
        }
        await record.model.hooks.lifecycle.onRecordSaved(record, changes);
        if (reload) {
            if (record.resId) {
                record.model._updateSimilarRecords(record, records[0]);
            }
            if (nextId) {
                record.model._patchConfig(record.config, { resId: nextId });
            }
            if (record.config.isRoot) {
                record.model.hooks.lifecycle.onWillLoadRoot(record.config);
            }
            record._setData(records[0], { orderBys });
        } else {
            record._values = markRaw({ ...record._values, ...record._changes });
            if ("id" in record.activeFields) {
                record._values.id = records[0].id;
            }
            for (const fieldName of Object.keys(record.activeFields)) {
                const field = record.fields[fieldName];
                if (
                    ["one2many", "many2many"].includes(field.type) &&
                    !field.relatedPropertyField
                ) {
                    record._changes[fieldName]?._clearCommands();
                }
            }
            record._clearChanges();
            record.data = { ...record._values };
        }
    } finally {
        record._saveInFlight = false;
    }
    return true;
}
