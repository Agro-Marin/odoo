// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_save */

import { markup } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { RequestEntityTooLargeError } from "@web/core/network/rpc";
import { modelLog } from "@web/core/utils/asset_log";

import { buildConcurrencyBaseline } from "./concurrency_baseline.js";
import { FetchRecordError } from "./errors.js";
import { getId, getSpecEvalContext, isX2Many } from "./field_context.js";
import { getFieldsSpec } from "./field_spec.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
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

const PENDING_COMMANDS_MAX_ITERATIONS = 100;

/**
 * @param {RelationalRecord} record
 */
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
 * @param {RelationalRecord} record
 * @returns {Generator<[string, any]>}
 */
function* x2manyLists(record) {
    for (const fieldName of Object.keys(record.activeFields)) {
        const field = record.fields[fieldName];
        if (!isX2Many(field) || field.relatedPropertyField) {
            continue;
        }
        const list = record.data[fieldName];
        if (list) {
            yield [fieldName, list];
        }
    }
}

/**
 * @param {RelationalRecord} record
 * @param {Set<any>} [seen]
 * @returns {Record<string, any>}
 */
function buildX2manyCommitSpec(record, seen = new Set()) {
    /** @type {Record<string, any>} */
    const spec = {};
    if (seen.has(record)) {
        return spec;
    }
    seen.add(record);
    for (const [fieldName, list] of x2manyLists(record)) {
        const nested = {};
        for (const child of Object.values(list._cache)) {
            Object.assign(nested, buildX2manyCommitSpec(child, seen));
        }
        const hasNested = Object.keys(nested).length > 0;
        if (!list._commands.length && !hasNested) {
            continue;
        }
        spec[fieldName] = hasNested ? { fields: nested } : {};
    }
    return spec;
}

/**
 * @param {RelationalRecord} record
 * @param {Record<string, any>} [values]
 * @param {Set<any>} [seen]
 */
function commitX2manyLists(record, values, seen = new Set()) {
    if (seen.has(record)) {
        return;
    }
    seen.add(record);
    for (const [fieldName, list] of x2manyLists(record)) {
        const serverValue = values?.[fieldName];
        if (serverValue === undefined) {
            list._clearCommands();
            continue;
        }
        list._commitSave(serverValue);
        for (const row of serverValue) {
            if (row && typeof row === "object") {
                const child = list._cache[row.id];
                if (child) {
                    commitX2manyLists(child, row, seen);
                }
            }
        }
    }
}

/**
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
        for (const [, list] of x2manyLists(record)) {
            list._clearCommands();
        }
        record._discardChanges();
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
            for (const [, list] of x2manyLists(record)) {
                list._clearCommands();
            }
            record._commitChanges();
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
                getSpecEvalContext(record.config),
                { orderBys },
            );
        } else {
            fieldSpec = buildX2manyCommitSpec(record);
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
            commitX2manyLists(record, records[0]);
            record._commitChanges(
                "id" in record.activeFields ? { id: records[0].id } : undefined,
            );
        }
    } finally {
        record._saveInFlight = false;
    }
    return true;
}
