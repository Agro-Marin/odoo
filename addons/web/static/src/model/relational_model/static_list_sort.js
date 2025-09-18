// @ts-check

/** @module @web/model/relational_model/static_list_sort - Sorting and resequencing logic extracted from StaticList */

/**
 * Record sorting, resequencing (drag-and-drop handle fields),
 * and sort-by-column logic for StaticList.
 *
 * Receives the StaticList instance as first argument (delegation pattern).
 */

import { pick } from "@web/core/utils/collections/objects";
import { compareRecords, computeNextOrderBy } from "./static_list_utils";

/** @import { StaticList } from "@web/model/relational_model/static_list" */

/**
 * Sort records by the given orderBy spec, loading missing field values as needed.
 * @param {StaticList} list
 * @param {any[]} [currentIds]
 * @param {any[]} [orderBy]
 */
export async function sort(list, currentIds = list.currentIds, orderBy = list.orderBy) {
    if (!orderBy.length) {
        return currentIds;
    }
    const fieldNames = orderBy.map((o) => o.name);
    const resIds = list._getResIdsToLoad(currentIds, fieldNames);
    if (resIds.length) {
        const activeFields = pick(list.activeFields, ...fieldNames);
        const config = { ...list.config, resIds, activeFields };
        const records = await list.model._loadRecords(config);
        for (const record of records) {
            list._createRecordDatapoint(record, { activeFields });
        }
    }
    const allRecords = currentIds.map((id) => list._cache[id]);
    const sortedRecords = allRecords.sort((r1, r2) =>
        compareRecords(r1, r2, orderBy, list.fields),
    );
    await list._load({
        orderBy,
        nextCurrentIds: sortedRecords.map((r) => r.resId || r._virtualId),
    });
    list._needsReordering = false;
}

/**
 * Resequence a record by moving it to a target position and updating handle field values.
 * @param {StaticList} list
 * @param {number|string} movedId
 * @param {number|string|null} targetId
 */
export async function resequence(list, movedId, targetId) {
    const records = [...list.records];
    const order = list.orderBy.find((o) => o.name === list.handleField);
    const asc = !order || order.asc;

    // Find indices
    const fromIndex = records.findIndex((r) => r.id === movedId);
    let toIndex = 0;
    if (targetId !== null) {
        const targetIndex = records.findIndex((r) => r.id === targetId);
        toIndex = fromIndex > targetIndex ? targetIndex + 1 : targetIndex;
    }

    const getSequence = (rec) => rec && rec.data[list.handleField];

    // Determine what records need to be modified
    const firstIndex = Math.min(fromIndex, toIndex);
    const lastIndex = Math.max(fromIndex, toIndex) + 1;
    let reorderAll = false;
    let lastSequence = (asc ? -1 : 1) * Infinity;
    for (let index = 0; index < records.length; index++) {
        const sequence = getSequence(records[index]);
        if (
            (asc && lastSequence >= sequence) ||
            (!asc && lastSequence <= sequence)
        ) {
            reorderAll = true;
            break;
        }
        lastSequence = sequence;
    }

    // Perform the resequence in the list of records
    const [record] = records.splice(fromIndex, 1);
    records.splice(toIndex, 0, record);

    // Creates the list of to modify
    let toReorder = records;
    if (!reorderAll) {
        toReorder = toReorder
            .slice(firstIndex, lastIndex)
            .filter((r) => r.id !== movedId);
        if (fromIndex < toIndex) {
            toReorder.push(record);
        } else {
            toReorder.unshift(record);
        }
    }
    if (!asc) {
        toReorder.reverse();
    }

    const sequences = toReorder.map(getSequence);
    const offset = sequences.length && Math.min(...sequences);

    const proms = [];
    for (const [i, record] of Object.entries(toReorder)) {
        proms.push(
            record._update(
                { [list.handleField]: offset + Number(i) },
                { withoutParentUpdate: true },
            ),
        );
    }
    await Promise.all(proms);

    await sort(list);
    await list._onUpdate();
}

/**
 * Toggle sort direction for a field, or switch to sorting by that field.
 * @param {StaticList} list
 * @param {string} fieldName
 */
export function sortBy(list, fieldName) {
    const orderBy = computeNextOrderBy(
        fieldName,
        list.orderBy,
        list._needsReordering,
    );
    return sort(list, list._currentIds, orderBy);
}
