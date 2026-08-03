// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/static_list_sort */

import { pick } from "@web/core/utils/collections/objects";

import { parseServerValue } from "./field_values.js";
import { computeResequencePlan } from "./resequence.js";
import { compareRecords, computeNextOrderBy } from "./static_list_utils.js";

/** @import { StaticList } from "@web/model/relational_model/static_list" */

/**
 * Order *currentIds*, loading whatever sort keys are missing first.
 *
 * A paginated x2many caches only the page it shows, so ordering the whole
 * relation means reading the sort columns of rows that are not on screen. Those
 * reads are deliberately narrow -- the sort needs `sequence`, not the row's
 * whole form spec -- and that is exactly why their results must NOT become
 * datapoints: a datapoint built from a narrow read is a record whose
 * `activeFields` disagrees with its list's, and it lands in `_cache` where
 * every other traversal will find it.
 *
 * So a narrow read produces a throwaway sort key instead, and only a read that
 * happens to cover the list's whole field set is promoted to a real datapoint
 * (which also keeps that case down to the single round trip it has always
 * taken). The keys are per-call: they cannot go stale because they do not
 * outlive the sort that fetched them.
 *
 * @param {StaticList} list
 * @param {any[]} [currentIds]
 * @param {any[]} [orderBy]
 */
export async function sort(list, currentIds = list.currentIds, orderBy = list.orderBy) {
    if (!orderBy.length) {
        return currentIds;
    }
    const fieldNames = orderBy.map((o) => o.name);
    /** @type {Map<any, { resId: any, data: Record<string, any> }>} */
    const sortKeys = new Map();
    const resIds = list._getResIdsToLoad(currentIds, fieldNames);
    if (resIds.length) {
        const activeFields = pick(list.activeFields, ...fieldNames);
        const sortSpecIsTotal = list.fieldNames.every((name) =>
            Object.hasOwn(activeFields, name),
        );
        const config = { ...list.config, resIds, activeFields };
        const records = await list.model._loadRecords(config, list.evalContext);
        for (const record of records) {
            const cached = list._cache[record.id];
            if (cached) {
                // Merge, never replace: an id is re-read here because its
                // datapoint was missing the sort column, so the fresh value has
                // to reach the comparator -- but the datapoint may also hold
                // the user's pending edits, its edit mode and its selection.
                cached._applyValues(record);
                continue;
            }
            if (sortSpecIsTotal) {
                list._createRecordDatapoint(record);
                continue;
            }
            /** @type {Record<string, any>} */
            const data = {};
            for (const name of fieldNames) {
                if (name in record) {
                    data[name] = parseServerValue(list.fields[name], record[name]);
                }
            }
            sortKeys.set(record.id, { resId: record.id, data });
        }
    }
    const cache = /** @type {Record<string, any>} */ (list._cache);
    // A datapoint wins over a sort key: it has just been refreshed above, and
    // it is the only one of the two that carries pending edits.
    const sortableOf = (/** @type {any} */ id) => cache[id] || sortKeys.get(id);
    const entries = currentIds
        .filter((/** @type {any} */ id) => sortableOf(id))
        .map((/** @type {any} */ id) => ({ id, sortable: sortableOf(id) }));
    entries.sort((a, b) =>
        compareRecords(a.sortable, b.sortable, orderBy, list.fields),
    );
    await list._load({
        orderBy,
        nextCurrentIds: entries.map((e) => e.id),
    });
    list.markReordered();
}

/**
 * @param {StaticList} list
 * @param {number|string} movedId
 * @param {number|string|null} targetId
 */
export async function resequence(list, movedId, targetId) {
    const order = list.orderBy.find((o) => o.name === list.handleField);
    const asc = !order || order.asc;

    const { toReorder, offset, fromIndex } = computeResequencePlan({
        records: list.records,
        movedId,
        targetId,
        getSequence: (rec) => rec?.data[list.handleField],
        asc,
    });

    if (fromIndex < 0) {
        return;
    }

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
 * @param {StaticList} list
 * @param {string} fieldName
 */
export function sortBy(list, fieldName) {
    const orderBy = computeNextOrderBy(fieldName, list.orderBy, list._needsReordering);
    return sort(list, list._currentIds, orderBy);
}
