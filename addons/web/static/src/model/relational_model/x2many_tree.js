// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/x2many_tree */

import { isX2Many } from "./field_context.js";

/** @import { RecordContract } from "./record_contract.js" */
/** @import { StaticListContract } from "./static_list_contract.js" */

/**
 * The record -> list -> record shape, in one place.
 *
 * The save path walks this tree three times for three different questions, and
 * open-coding the walk each time let the three drift: two disagreed on whether
 * property-backed lists are members, and each carried its own cycle guard. A
 * record can appear under several lists (and a list under several records via
 * the cache), so the guard is not optional -- it is the thing that makes the
 * walk terminate.
 */

/**
 * Every x2many list held by *record*, INCLUDING the ones backing a `properties`
 * field. Command replay is staged on those too, so anything that has to be
 * quiesced before a save must see them.
 *
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
 * The x2many lists that are fields of *record* in their own right. A
 * property-backed list is excluded: it is a facet of the `properties` field,
 * which carries its own value, so it is neither written nor committed
 * separately.
 *
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
 * Pending command-replay promises anywhere under *record*.
 *
 * @param {RecordContract} record
 * @returns {Promise<unknown>[]}
 */
export function collectPendingCommands(record) {
    /** @type {Promise<unknown>[]} */
    const proms = [];
    const seen = new Set();
    /** @param {RecordContract} current */
    const visit = (current) => {
        for (const [, list] of allX2manyLists(current)) {
            if (seen.has(list)) {
                continue;
            }
            seen.add(list);
            if (list.pendingCommands) {
                proms.push(list.pendingCommands);
            }
            for (const subRecord of list.cachedRecords) {
                if (!seen.has(subRecord)) {
                    seen.add(subRecord);
                    visit(subRecord);
                }
            }
        }
    };
    visit(record);
    return proms;
}

/**
 * The `web_save` specification for a `reload: false` save: name only the
 * x2many fields whose result actually has to come back, so the round trip does
 * not re-read the whole form.
 *
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
 * Adopt the server's post-save x2many values through the subtree. A field the
 * server did not report was still written, so its staged commands are dropped
 * rather than carried into the next save.
 *
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
