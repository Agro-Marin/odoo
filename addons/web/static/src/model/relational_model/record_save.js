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
import { getBasicEvalContext, getId, isX2Many } from "./field_context.js";
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
        if (!isX2Many(field)) {
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
        await waitForPendingCommands(record);
    }
    for (const fieldName of Object.keys(record.activeFields)) {
        const field = record.fields[fieldName];
        if (isX2Many(field) && !field.relatedPropertyField) {
            record.data[fieldName]._abandonRecords();
        }
    }
    if (!record._checkValidity({ displayNotification: true })) {
        return false;
    }
    const changes = record._getChanges();
    delete changes.id;
    record._urgentBeaconFired = false;
    const concurrencyBaseline = buildConcurrencyBaseline(record, Object.keys(changes));
    if (!creation && !Object.keys(changes).length) {
        if (nextId) {
            await record.model.load({ resId: nextId });
            return true;
        }
        for (const fieldName of Object.keys(record.activeFields)) {
            const field = record.fields[fieldName];
            if (isX2Many(field) && !field.relatedPropertyField) {
                record._changes[fieldName]?._clearCommands();
            }
        }
        record._clearChanges();
        record.data = { ...record._values };
        record._textValues = markRaw({ ...record._initialTextValues });
        record._setEvalContext();
        return true;
    }
    if (
        record.model.urgentSave.isActive &&
        record.model.useSendBeaconToSaveUrgently &&
        !record.model.env.inDialog &&
        record.resId
    ) {
        const route = `/web/dataset/call_kw/${record.resModel}/web_save`;
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
            record._urgentBeaconFired = true;
            record._values = markRaw({ ...record._values, ...record._changes });
            for (const fieldName of Object.keys(record.activeFields)) {
                const field = record.fields[fieldName];
                if (isX2Many(field) && !field.relatedPropertyField) {
                    record._changes[fieldName]?._clearCommands();
                }
            }
            record._clearChanges();
            record.data = { ...record._values };
            record._setEvalContext();
            record._initialTextValues = markRaw({ ...record._textValues });
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
    const canProceed = await record.model.hooks.lifecycle.onWillSaveRecord(
        record,
        changes,
    );
    const beaconFiredWhileParked = record._urgentBeaconFired;
    record._urgentBeaconFired = false;
    if (canProceed === false) {
        return false;
    }
    if (beaconFiredWhileParked) {
        return true;
    }
    record._saveInFlight = true;
    try {
        /** @type {Record<string, any>} */
        const orderBys = {};
        if (!nextId) {
            const fieldNames = record.fieldNames;
            for (const fieldName of fieldNames) {
                if (isX2Many(record.fields[fieldName])) {
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
        if (record.config.isRoot) {
            record.model._patchConfig(record.config, { loadId: getId("load") });
        }
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
                if (isX2Many(field) && !field.relatedPropertyField) {
                    record._changes[fieldName]?._clearCommands();
                }
            }
            record._clearChanges();
            record.data = { ...record._values };
            record._setEvalContext();
            record._initialTextValues = markRaw({ ...record._textValues });
        }
    } finally {
        record._saveInFlight = false;
    }
    return true;
}
