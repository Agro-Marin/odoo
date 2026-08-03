// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_save */

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
    if (!record.model.urgentSave.isActive) {
        await waitForPendingCommands(record);
    }
    for (const [, list] of x2manyLists(record)) {
        list._abandonRecords();
    }
    if (!record._checkValidity({ displayNotification: true })) {
        return false;
    }
    const changes = record._getChanges();
    record.saveState.clearBeacon();
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
            record.saveState.noteBeaconFired();
            for (const [, list] of x2manyLists(record)) {
                list._clearCommands();
            }
            record._commitChanges();
        } else {
            record.model.displayUrgentSaveNotification(
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
    const beaconFiredWhileParked = record.saveState.consumeBeaconFired();
    if (canProceed === false) {
        return false;
    }
    if (beaconFiredWhileParked) {
        return true;
    }
    record.saveState.enter();
    try {
        /** @type {Record<string, any>} */
        const orderBys = {};
        if (!nextId) {
            for (const [fieldName, list] of x2manyLists(record)) {
                orderBys[fieldName] = list.orderBy;
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
            fieldSpec = buildCommitSpec(record);
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
            commitSubtree(record, records[0]);
            record._commitChanges(
                "id" in record.activeFields ? { id: records[0].id } : undefined,
            );
        }
    } finally {
        record.saveState.exit();
    }
    return true;
}
