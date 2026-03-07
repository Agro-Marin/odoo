// @ts-check

/** @module @web/model/relational_model/record_save - Save logic extracted from RelationalRecord */

/**
 * Record persistence logic: web_save RPC, sendBeacon for urgent saves,
 * creation flow, reload, and error handling.
 * Receives the RelationalRecord instance as first argument (delegation pattern).
 */

import { markRaw, markup } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { FetchRecordError } from "./errors";
import { getBasicEvalContext } from "./field_context";
import { getFieldsSpec } from "./field_spec";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Persist a record via web_save. Handles creation, sendBeacon for urgent saves,
 * field spec computation, and post-save reload.
 * @param {RelationalRecord} record
 * @param {{ reload?: boolean, onError?: (e: Error, actions: { discard: () => void, retry: () => any }) => any, nextId?: number }} [options]
 * @returns {Promise<boolean>}
 */
export async function save(record, { reload = true, onError, nextId } = {}) {
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
    // before saving, abandon new invalid, untouched records in x2manys
    for (const fieldName in record.activeFields) {
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
    if (!creation && !Object.keys(changes).length) {
        if (nextId) {
            return record.model.load({ resId: nextId });
        }
        record._changes = markRaw({});
        record.data = { ...record._values };
        record.dirty = false;
        return true;
    }
    if (
        record.model._urgentSave &&
        record.model.useSendBeaconToSaveUrgently &&
        !record.model.env.inDialog
    ) {
        // We are trying to save urgently because the user is closing the page. To
        // ensure that the save succeeds, we can't do a classic rpc, as these requests
        // can be cancelled (payload too heavy, network too slow, computer too fast...).
        // We instead use sendBeacon, which isn't cancellable. However, it has limited
        // payload (typically < 64k). So we try to save with sendBeacon, and if it
        // doesn't work, we will prevent the page from unloading.
        const route = `/web/dataset/call_kw/${record.resModel}/web_save`;
        const params = {
            model: record.resModel,
            method: "web_save",
            args: [record.resId ? [record.resId] : [], changes],
            kwargs: { context: record.context, specification: {} },
        };
        const data = { jsonrpc: "2.0", method: "call", params };
        const blob = new Blob([JSON.stringify(data)], {
            type: "application/json",
        });
        const succeeded = navigator.sendBeacon(route, blob);
        if (succeeded) {
            record._changes = markRaw({});
            record.dirty = false;
        } else {
            record.model._closeUrgentSaveNotification =
                record.model.hooks.onDisplayUrgentSave(
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
    const canProceed = await record.model.hooks.onWillSaveRecord(record, changes);
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
        if (onError) {
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
        throw new FetchRecordError([/** @type {number} */ (nextId || record.resId)]);
    }
    if (creation) {
        const resId = records[0].id;
        const resIds = [...record.resIds, resId];
        record.model._updateConfig(record.config, { resId, resIds }, { reload: false });
    }
    await record.model.hooks.onRecordSaved(record, changes);
    if (reload) {
        if (record.resId) {
            record.model._updateSimilarRecords(record, records[0]);
        }
        if (nextId) {
            record.model._updateConfig(
                record.config,
                { resId: nextId },
                { reload: false },
            );
        }
        if (record.config.isRoot) {
            record.model.hooks.onWillLoadRoot(record.config);
        }
        record._setData(records[0], { orderBys });
    } else {
        record._values = markRaw({ ...record._values, ...record._changes });
        if ("id" in record.activeFields) {
            record._values.id = records[0].id;
        }
        for (const fieldName in record.activeFields) {
            const field = record.fields[fieldName];
            if (
                ["one2many", "many2many"].includes(field.type) &&
                !field.relatedPropertyField
            ) {
                record._changes[fieldName]?._clearCommands();
            }
        }
        record._changes = markRaw({});
        record.data = { ...record._values };
        record.dirty = false;
    }
    return true;
}
