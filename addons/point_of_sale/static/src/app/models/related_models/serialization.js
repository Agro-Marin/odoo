/** @odoo-module native */
import { serializeDate, serializeDateTime } from "@web/core/l10n/dates";

import { DATE_TIME_TYPE, X2MANY_TYPES } from "./utils.js";
const deepSerialization = (
    record,
    opts,
    { serialized = {}, uuidMapping = {}, parentRelInverseName = null, stack = [] },
) => {
    const result = {};
    const { fields, name: currentModel } = record.model;
    const DYNAMIC_MODELS = opts.dynamicModels;
    const recursiveSerialize = (childRecord, parentRelInverseName) =>
        deepSerialization(childRecord, opts, {
            serialized,
            uuidMapping,
            parentRelInverseName,
            stack,
        });

    // The mutations that mark records clean (_dirty = false) and consume the
    // unlink/delete commands must not happen until the payload has actually
    // reached the server. Route them through scheduleClear: by default they run
    // inline (unchanged behaviour), but a caller can pass opts.deferClear with an
    // opts.clearActions array to collect them and apply them only once the RPC
    // succeeds. Otherwise a sync that throws (e.g. ConnectionLostError) would
    // clear the dirty flags and drop the commands for a payload the backend never
    // received, permanently losing those edits on the retry. keepCommands keeps
    // serialization fully pure (never clears) for local clones.
    const scheduleClear = (fn) => {
        if (opts.keepCommands) {
            return;
        }
        if (opts.deferClear) {
            opts.clearActions.push(fn);
        } else {
            fn();
        }
    };

    // We only care about the fields present in python model
    for (const [fieldName, field] of Object.entries(fields)) {
        if (field.local || field.related || field.compute || field.dummy) {
            continue;
        }

        const relatedModel = field.relation;
        const targetModel = field.model;
        const modelCommands = record.models.commands[currentModel];

        if (relatedModel) {
            if (!record.models[relatedModel]) {
                // Ignore not "loaded" model
                continue;
            }

            if (DYNAMIC_MODELS.includes(relatedModel) && !serialized[relatedModel]) {
                serialized[relatedModel] = {};
            }
        }
        if (DYNAMIC_MODELS.includes(currentModel) && !serialized[currentModel]) {
            serialized[currentModel] = { [record.uuid]: record.uuid };
        }
        if (DYNAMIC_MODELS.includes(targetModel) && !uuidMapping[targetModel]) {
            uuidMapping[targetModel] = {};
        }
        if (X2MANY_TYPES.has(field.type) && record[fieldName]) {
            if (DYNAMIC_MODELS.includes(relatedModel)) {
                const toUpdate = [];
                const toCreate = [];

                for (const childRecord of record[fieldName]) {
                    if (serialized[relatedModel][childRecord.uuid]) {
                        continue;
                    }

                    if (childRecord.isSynced && childRecord._dirty) {
                        toUpdate.push(childRecord);
                        // Epoch guard: only mark clean if the record was not
                        // edited again between serialization and the commit
                        // (i.e. while the sync RPC was in flight).
                        const epoch = childRecord._dirtyEpoch;
                        scheduleClear(() => {
                            if (childRecord._dirtyEpoch === epoch) {
                                childRecord._markClean();
                            }
                        });
                    } else if (!childRecord.isSynced) {
                        toCreate.push(childRecord);
                    }
                    serialized[relatedModel][childRecord.uuid] = childRecord.uuid;
                }
                // The stack defers processing of x2many relationships to ensure objects are only serialized
                // once in their first encountered parent, preventing redundant serialization.
                stack.push([
                    result,
                    fieldName,
                    () => [
                        ...(result[fieldName] || []),
                        ...toUpdate.map((childRecord) => [
                            1,
                            childRecord.id,
                            recursiveSerialize(childRecord, field.inverse_name),
                        ]),
                        ...toCreate.map((childRecord) => [
                            0,
                            0,
                            recursiveSerialize(childRecord, field.inverse_name),
                        ]),
                    ],
                ]);
            } else {
                result[fieldName] = record[fieldName]
                    .filter((childRecord) => childRecord.id)
                    .map((childRecord) => {
                        if (!childRecord.isSynced) {
                            throw new Error(
                                `Trying to create a non serializable record '${relatedModel}'`,
                            );
                        }
                        return childRecord.id;
                    });
            }

            if (
                modelCommands.unlink.has(fieldName) ||
                modelCommands.delete.has(fieldName)
            ) {
                result[fieldName] = result[fieldName] || [];
                const processRecords = (records, cmdCode) => {
                    for (const { id, parentId } of records) {
                        const isAlreadyDeleted =
                            serialized[relatedModel]?.["_deleted_" + id];
                        if (parentId === record.id && !isAlreadyDeleted) {
                            const isCascadeDelete =
                                record.models[relatedModel]?.fields[field.inverse_name]
                                    ?.ondelete;
                            if (isCascadeDelete) {
                                serialized[relatedModel]["_deleted_" + id] = true;
                            }
                            result[fieldName].push([cmdCode, id]);
                        }
                    }
                };
                processRecords(modelCommands.unlink.get(fieldName) || [], 3);
                processRecords(modelCommands.delete.get(fieldName) || [], 2);

                for (const commands of [modelCommands.unlink, modelCommands.delete]) {
                    if (opts.keepCommands) {
                        continue;
                    }
                    // Capture the exact entries consumed by THIS serialization;
                    // the commit removes only those from the live list.
                    // Overwriting with the serialize-time remainder would
                    // destroy commands added while the RPC was in flight (a
                    // line deleted mid-sync would never be unlinked
                    // server-side and would resurrect on the next fetch).
                    const commandList = commands.get(fieldName) || [];
                    const consumed = new Set(
                        commandList.filter(({ parentId }) => parentId === record.id),
                    );

                    scheduleClear(() => {
                        const remaining = (commands.get(fieldName) || []).filter(
                            (cmd) => !consumed.has(cmd),
                        );
                        if (remaining.length) {
                            commands.set(fieldName, remaining);
                        } else {
                            commands.delete(fieldName);
                        }
                    });
                }
            }
            continue;
        }

        if (field.type === "many2one") {
            const recordId = record[fieldName]?.id;
            if (DYNAMIC_MODELS.includes(relatedModel) && record[fieldName]) {
                if (
                    fieldName !== parentRelInverseName && //mapping not needed for direct child
                    record.uuid &&
                    serialized[relatedModel][record[fieldName].uuid]
                ) {
                    if (!record[fieldName].isSynced) {
                        //  mapping is only needed for newly created records
                        uuidMapping[targetModel][record.uuid] ??= {};
                        uuidMapping[targetModel][record.uuid][fieldName] =
                            record[fieldName].uuid;
                    }
                }
                serialized[relatedModel][record[fieldName].uuid] =
                    record[fieldName].uuid;
            }
            if (typeof recordId === "number" && recordId >= 0) {
                result[fieldName] = recordId;
            } else if (record[fieldName] === undefined) {
                result[fieldName] = false;
            }
            continue;
        }
        if (DATE_TIME_TYPE.has(field.type) && typeof record[fieldName] === "object") {
            result[fieldName] =
                field.type === "datetime"
                    ? serializeDateTime(record[fieldName])
                    : serializeDate(record[fieldName]);
            continue;
        }
        if (fieldName === "id") {
            if (typeof record[fieldName] === "number") {
                result[fieldName] = record[fieldName];
            }
            continue;
        }
        result[fieldName] = record[fieldName] !== undefined ? record[fieldName] : false;
    }

    while (stack.length) {
        const [res, key, getValue] = stack.pop();
        res[key] = getValue();
    }

    const recordEpoch = record._dirtyEpoch;
    scheduleClear(() => {
        if (record._dirtyEpoch === recordEpoch) {
            record._markClean();
        }
    });

    // Cleanup: remove empty entries from uuidMapping.
    for (const key in uuidMapping) {
        if (
            uuidMapping[key] &&
            typeof uuidMapping[key] === "object" &&
            Object.keys(uuidMapping[key]).length === 0
        ) {
            delete uuidMapping[key];
        }
    }

    return result;
};

export const ormSerialization = (record, opts) => {
    const uuidMapping = {};
    const result = deepSerialization(record, opts, {
        uuidMapping,
    });
    if (Object.keys(uuidMapping).length !== 0) {
        result.relations_uuid_mapping = uuidMapping;
    }
    return result;
};
