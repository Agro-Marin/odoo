// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/static_list_sort - Sorting and resequencing logic extracted from StaticList */

/**
 * Record sorting, resequencing (drag-and-drop handle fields),
 * and sort-by-column logic for StaticList.
 *
 * Receives the StaticList instance as first argument (delegation pattern).
 */

import { pick } from "@web/core/utils/collections/objects";

import { computeResequencePlan } from "./resequence.js";
import { compareRecords, computeNextOrderBy } from "./static_list_utils.js";

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
    const order = list.orderBy.find((o) => o.name === list.handleField);
    const asc = !order || order.asc;

    const { toReorder, offset } = computeResequencePlan({
        records: list.records,
        movedId,
        targetId,
        getSequence: (rec) => rec?.data[list.handleField],
        asc,
    });

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
    const orderBy = computeNextOrderBy(fieldName, list.orderBy, list._needsReordering);
    return sort(list, list._currentIds, orderBy);
}
