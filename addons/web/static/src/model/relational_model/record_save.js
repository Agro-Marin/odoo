// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { RequestEntityTooLargeError } from "@web/core/network/rpc";
import { _t } from "@web/core/translation";
import { modelLog } from "@web/core/utils/asset_log";

import { buildConcurrencyBaseline } from "./concurrency_baseline.js";
import { FetchRecordError } from "./errors.js";
import { getId, getSpecEvalContext } from "./field_context.js";
import { getFieldsSpec } from "./field_spec.js";
import {
    buildCommitSpec,
    collectPendingCommands,
    commitSubtree,
    healSubtreeReplayFailures,
    x2manyLists,
} from "./x2many_tree.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

const PENDING_COMMANDS_MAX_ITERATIONS = 100;

/**
 * @param {RelationalRecord} record
 */
async function waitForPendingCommands(record) {
    for (let i = 0; i < PENDING_COMMANDS_MAX_ITERATIONS; i++) {
        const proms = collectPendingCommands(record);
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
 * @returns {Promise<boolean>}
 */
async function quiesceAndValidate(record) {
    if (!record.model.urgentSave.isActive) {
        await waitForPendingCommands(record);
    }
    for (const [, list] of x2manyLists(record)) {
        list._abandonRecords();
    }
    return record._checkValidity({ displayNotification: true });
}

/**
 * @param {RelationalRecord} record
 * @param {number | undefined} nextId
 * @returns {Promise<true>}
 */
async function settleWithoutSaving(record, nextId) {
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

/**
 * @param {RelationalRecord} record
 * @returns {boolean}
 */
function shouldSaveByBeacon(record) {
    return Boolean(
        record.model.urgentSave.isActive &&
        record.model.useSendBeaconToSaveUrgently &&
        !record.model.env.inDialog &&
        record.resId,
    );
}

/**
 * @param {RelationalRecord} record
 * @param {Record<string, any>} changes
 * @param {Record<string, any>} concurrencyBaseline
 * @returns {boolean}
 */
function saveByBeacon(record, changes, concurrencyBaseline) {
    const route = `/web/dataset/call_kw/${record.resModel}/web_save`;
    const params = {
        model: record.resModel,
        method: "web_save",
        args: [record.resId ? [record.resId] : [], changes],
        kwargs: {
            context: record.context,
            specification: {},
            known_values: concurrencyBaseline,
        },
    };
    const blob = new Blob(
        [JSON.stringify({ jsonrpc: "2.0", method: "call", params })],
        {
            type: "application/json",
        },
    );
    const succeeded = navigator.sendBeacon(route, blob);
    if (succeeded) {
        record.saveState.noteBeaconFired();
        for (const [, list] of x2manyLists(record)) {
            list._clearCommands();
        }
        record._commitChanges();
        return true;
    }
    record.model.displayUrgentSaveNotification(
        _t(
            `Heads up! Your recent changes are too large to save automatically. Please click the %(upload_icon)s button now to ensure your work is saved before you exit this tab.`,
            {
                upload_icon: markup`<i class="fa-solid fa-cloud-arrow-up"></i>`,
            },
        ),
    );
    return false;
}

/**
 * @param {RelationalRecord} record
 * @param {number | undefined} nextId
 * @returns {Record<string, any>}
 */
function collectOrderBys(record, nextId) {
    /** @type {Record<string, any>} */
    const orderBys = {};
    if (nextId) {
        return orderBys;
    }
    for (const [fieldName, list] of x2manyLists(record)) {
        orderBys[fieldName] = list.orderBy;
    }
    return orderBys;
}

/**
 * @param {RelationalRecord} record
 * @param {{ reload: boolean, nextId: number | undefined, orderBys: Record<string, any>,
 *           concurrencyBaseline: Record<string, any> }} params
 * @returns {Record<string, any>}
 */
function buildSaveKwargs(record, { reload, nextId, orderBys, concurrencyBaseline }) {
    /** @type {Record<string, any>} */
    const kwargs = {
        context: record.context,
        specification: reload
            ? getFieldsSpec(
                  record.activeFields,
                  record.fields,
                  getSpecEvalContext(record.config),
                  { orderBys },
              )
            : buildCommitSpec(record),
        next_id: nextId,
    };
    if (record.resId) {
        kwargs.known_values = concurrencyBaseline;
    }
    return kwargs;
}

/**
 * @param {RelationalRecord} record
 * @param {Record<string, any>[]} records
 * @param {{ reload: boolean, nextId: number | undefined, creation: boolean,
 *           changes: Record<string, any>, orderBys: Record<string, any> }} params
 * @returns {Promise<void>}
 */
async function applySaveResult(
    record,
    records,
    { reload, nextId, creation, changes, orderBys },
) {
    if (reload && !records.length) {
        throw new FetchRecordError([/** @type {number} */ (nextId || record.resId)]);
    }
    if (creation) {
        const resId = records[0].id;
        record.model._patchConfig(record.config, {
            resId,
            resIds: [...(record.resIds ?? []), resId],
        });
    }
    await record.model.notifyLifecycle("onRecordSaved", record, changes);
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
            record.model.notifyLifecycleSync("onWillLoadRoot", record.config);
        }
        record._setData(records[0], { orderBys });
    } else {
        commitSubtree(record, records[0]);
        record._commitChanges(
            "id" in record.activeFields ? { id: records[0].id } : undefined,
        );
    }
    healSubtreeReplayFailures(record);
}

/**
 * @param {RelationalRecord} record
 * @param {{ reload?: boolean, onError?: (e: Error, actions: { discard: () => void, retry: () => any }) => any, nextId?: number }} [options]
 * @returns {Promise<boolean>}
 */
export async function save(record, { reload = true, onError, nextId } = {}) {
    modelLog("save", record.resModel, record.resId || "(new)");
    record.model.closeUrgentSaveNotification();
    const creation = !record.resId;
    if (nextId) {
        if (creation) {
            throw new Error("Cannot set nextId on a new record");
        }
        reload = true;
    }
    if (!(await quiesceAndValidate(record))) {
        return false;
    }

    const changes = record._getChanges();
    record.saveState.clearBeacon();
    const concurrencyBaseline = buildConcurrencyBaseline(record, Object.keys(changes));
    if (!creation && !Object.keys(changes).length) {
        return settleWithoutSaving(record, nextId);
    }
    if (shouldSaveByBeacon(record)) {
        return saveByBeacon(record, changes, concurrencyBaseline);
    }

    const canProceed = await record.model.notifyLifecycle(
        "onWillSaveRecord",
        record,
        changes,
    );
    const beaconFiredWhileParked = record.saveState.consumeBeaconFired();
    if (canProceed === false) {
        return false;
    }
    if (beaconFiredWhileParked) {
        return true;
    }

    record.saveState.enter();
    try {
        const orderBys = collectOrderBys(record, nextId);
        const kwargs = buildSaveKwargs(record, {
            reload,
            nextId,
            orderBys,
            concurrencyBaseline,
        });
        /** @type {Record<string, any>[]} */
        let records;
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
        await applySaveResult(record, records, {
            reload,
            nextId,
            creation,
            changes,
            orderBys,
        });
    } finally {
        record.saveState.exit();
    }
    return true;
}
