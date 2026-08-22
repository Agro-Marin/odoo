// @ts-check
/** @odoo-module native */

import { isX2Many } from "@web/core/field_types";

/** @import { RecordContract } from "./record_contract.js" */
/** @import { StaticListContract } from "./static_list_contract.js" */

/**
 * @param {RecordContract} record
 * @returns {Generator<[string, StaticListContract]>}
 */
export function* allX2manyLists(record) {
    for (const fieldName of Object.keys(record.activeFields)) {
        if (!isX2Many(record.fields[fieldName])) {
            continue;
        }
        const list = record.data[fieldName];
        if (list) {
            yield [fieldName, list];
        }
    }
}

/**
 * @param {RecordContract} record
 * @returns {Generator<[string, StaticListContract]>}
 */
export function* x2manyLists(record) {
    for (const [fieldName, list] of allX2manyLists(record)) {
        if (!record.fields[fieldName].relatedPropertyField) {
            yield [fieldName, list];
        }
    }
}

/**
 * @param {RecordContract} record
 * @returns {Generator<[string, StaticListContract]>}
 */
export function* walkX2manySubtree(record) {
    const seen = new Set();
    /**
     * @param {RecordContract} current
     * @returns {Generator<[string, StaticListContract]>}
     */
    function* visit(current) {
        for (const [fieldName, list] of allX2manyLists(current)) {
            if (seen.has(list)) {
                continue;
            }
            seen.add(list);
            yield [fieldName, list];
            for (const subRecord of list.cachedRecords) {
                if (!seen.has(subRecord)) {
                    seen.add(subRecord);
                    yield* visit(subRecord);
                }
            }
        }
    }
    yield* visit(record);
}

/**
 * @param {RecordContract} record
 * @returns {Promise<unknown>[]}
 */
export function collectPendingCommands(record) {
    /** @type {Promise<unknown>[]} */
    const proms = [];
    for (const [, list] of walkX2manySubtree(record)) {
        if (list.pendingCommands) {
            proms.push(list.pendingCommands);
        }
    }
    return proms;
}

/**
 * @param {RecordContract} record
 */
export function healSubtreeReplayFailures(record) {
    for (const [, list] of walkX2manySubtree(record)) {
        list.healFailedReplay();
    }
}

/**
 * @param {RecordContract} record
 * @param {Set<unknown>} [seen]
 * @returns {Record<string, any>}
 */
export function buildCommitSpec(record, seen = new Set()) {
    /** @type {Record<string, any>} */
    const spec = {};
    if (seen.has(record)) {
        return spec;
    }
    seen.add(record);
    for (const [fieldName, list] of x2manyLists(record)) {
        const nested = {};
        for (const child of list.cachedRecords) {
            Object.assign(nested, buildCommitSpec(child, seen));
        }
        const hasNested = Object.keys(nested).length > 0;
        if (!list.hasStagedCommands && !hasNested) {
            continue;
        }
        spec[fieldName] = hasNested ? { fields: nested } : {};
    }
    return spec;
}

/**
 * @param {RecordContract} record
 * @param {Record<string, any>} [values]
 * @param {Set<unknown>} [seen]
 */
export function commitSubtree(record, values, seen = new Set()) {
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
                const child = list.getCachedRecord(row.id);
                if (child) {
                    commitSubtree(child, row, seen);
                }
            }
        }
    }
}
