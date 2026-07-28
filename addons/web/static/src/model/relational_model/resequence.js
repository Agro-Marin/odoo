// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/resequence - Reorders records by sequence field via drag-and-drop position changes */

/**
 * Compute the plan for moving one record to a new position in a
 * sequence-ordered list: which records must receive a new sequence value,
 * and from which offset the new values start.
 *
 * Pure — does not mutate ``records``. Shared by the server-backed
 * {@link resequence} below and by StaticList's in-memory resequencing
 * (static_list_sort.js).
 *
 * Minimizes writes: if sequence values are strictly monotonic, only records
 * between the source and target positions are rewritten. Otherwise
 * (duplicates, wrong-direction gaps, or a missing sequence value), every
 * record is rewritten (``reorderAll``).
 *
 * @param {Object} params
 * @param {Array<{id: number | string}>} params.records - Records in their
 *   current visual order.
 * @param {number | string} params.movedId - The id of the record being moved.
 * @param {number | string | null} [params.targetId] - The id of the target
 *   position: the record is placed after it. ``null``/``undefined`` moves the
 *   record to the first position.
 * @param {(record: any) => number} params.getSequence - Read a record's
 *   current sequence value.
 * @param {boolean} [params.asc] - Whether the list is sorted ascending.
 * @returns {{
 *   toReorder: any[],
 *   offset: number,
 *   fromIndex: number,
 *   toIndex: number,
 *   reorderAll: boolean,
 * }} ``toReorder`` lists the records to rewrite, in ascending target-sequence
 *   order; new sequences are ``offset + index``. ``fromIndex``/``toIndex``
 *   are the source and destination indices in ``records``.
 */
export function computeResequencePlan({
    records,
    movedId,
    targetId,
    getSequence,
    asc = true,
}) {
    const fromIndex = records.findIndex((r) => r.id === movedId);
    let toIndex = 0;
    if (targetId !== null && targetId !== undefined) {
        const targetIndex = records.findIndex((r) => r.id === targetId);
        toIndex = fromIndex > targetIndex ? targetIndex + 1 : targetIndex;
    }

    const firstIndex = Math.min(fromIndex, toIndex);
    const lastIndex = Math.max(fromIndex, toIndex) + 1;
    let reorderAll = records.some((record) => getSequence(record) === undefined);
    if (!reorderAll) {
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
    }

    const reordered = [...records];
    const [record] = reordered.splice(fromIndex, 1);
    reordered.splice(toIndex, 0, record);

    let toReorder = reordered;
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

    const sequences = toReorder.map(getSequence).filter((s) => s != null && !isNaN(s));
    const offset = sequences.length ? Math.min(...sequences) : 0;

    return { toReorder, offset, fromIndex, toIndex, reorderAll };
}

/**
 * Resequence records based on provided parameters.
 *
 * @param {Object} params
 * @param {Array} params.records - The list of records to resequence.
 * @param {string} params.resModel - The model to be used for resequencing.
 * @param {Object} params.orm
 * @param {string} params.fieldName - The field used to handle the sequence.
 * @param {number} params.movedId - The id of the record being moved.
 * @param {number} [params.targetId] - The id of the target position, the record will be resequenced
 *                                     after the target. If undefined, the record will be resequenced
 *                                     as the first record.
 * @param {Boolean} [params.asc] - Resequence in ascending or descending order
 * @param {(record: any) => number} [params.getSequence] - Function to get the sequence of a record.
 * @param {(record: any) => number} [params.getResId] - Function to get the resID of the record.
 * @param {Object} [params.context]
 * @returns {Promise<any>} - The list of the resequenced fieldName
 */
export async function resequence({
    records,
    resModel,
    orm,
    fieldName,
    movedId,
    targetId,
    asc = true,
    getSequence = (record) => record[fieldName],
    getResId = (record) => record.id,
    context,
}) {
    const { toReorder, offset, fromIndex, toIndex, reorderAll } = computeResequencePlan(
        { records, movedId, targetId, getSequence, asc },
    );

    if (fromIndex < 0) {
        return [];
    }

    const originalOrder = [...records];
    const record = records[fromIndex];
    if (fromIndex !== toIndex) {
        records.splice(fromIndex, 1);
        records.splice(toIndex, 0, record);
    }
    if (!asc && reorderAll) {
        records.reverse();
    }

    const resIds = toReorder.map((d) => getResId(d)).filter((id) => id && !isNaN(id));

    try {
        return await orm.webResequence(resModel, resIds, {
            field_name: fieldName,
            offset,
            context,
            specification: { [fieldName]: {} },
        });
    } catch (error) {
        records.splice(0, records.length, ...originalOrder);
        throw error;
    }
}
