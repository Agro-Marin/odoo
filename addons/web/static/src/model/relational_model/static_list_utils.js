// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/static_list_utils */

/**
 * @param {any} v1
 * @param {any} v2
 * @param {string} fieldType
 * @returns {boolean}
 */

import { x2ManyCommands } from "./commands.js";

/** @import { DatapointId } from "@web/model/types" */
/** @import { RelationalRecord } from "./record.js" */

/**
 * The id a record answers to inside its list: its resId once the server knows
 * it, its virtual id until then. Exactly one of the two is set.
 *
 * The single place that reads `_virtualId` across a module boundary, which is
 * why it is a function here rather than a getter on the record: the static-list
 * suites drive these paths with plain-object records, and a getter would make
 * every one of them carry an accessor to say what two fields already say.
 *
 * @param {RelationalRecord} record
 * @returns {DatapointId}
 */
export function listId(record) {
    return /** @type {DatapointId} */ (record.resId || record._virtualId);
}

function compareFieldValues(v1, v2, fieldType) {
    if (fieldType === "many2one") {
        v1 = v1 ? v1.display_name : "";
        v2 = v2 ? v2.display_name : "";
    } else if (
        fieldType === "integer" ||
        fieldType === "float" ||
        fieldType === "monetary"
    ) {
        v1 = v1 ?? 0;
        v2 = v2 ?? 0;
    } else {
        v1 = v1 ?? "";
        v2 = v2 ?? "";
    }
    return v1 < v2;
}

/**
 * @param {Object} r1
 * @param {Object} r2
 * @param {import("@web/core/utils/order_by").OrderTerm[]} orderBy
 * @param {Object} fields
 * @returns {number}
 */
export function compareRecords(r1, r2, orderBy, fields) {
    const { name, asc } = orderBy[0];
    function getValue(record, fieldName) {
        return fieldName === "id" ? record.resId : record.data[fieldName];
    }
    const v1 = asc ? getValue(r1, name) : getValue(r2, name);
    const v2 = asc ? getValue(r2, name) : getValue(r1, name);
    if (compareFieldValues(v1, v2, fields[name].type)) {
        return -1;
    }
    if (compareFieldValues(v2, v1, fields[name].type)) {
        return 1;
    }
    if (orderBy.length > 1) {
        return compareRecords(r1, r2, orderBy.slice(1), fields);
    }
    return 0;
}

/**
 * @param {string} fieldName
 * @param {import("@web/core/utils/order_by").OrderTerm[]} currentOrderBy
 * @param {boolean} needsReordering
 * @param {Object} [options]
 * @param {import("@web/core/utils/order_by").OrderTerm[]} [options.resetOrderBy]
 * @returns {import("@web/core/utils/order_by").OrderTerm[]}
 */
export function computeNextOrderBy(
    fieldName,
    currentOrderBy,
    needsReordering,
    { resetOrderBy = [{ name: "id", asc: true }] } = {},
) {
    let orderBy = [...currentOrderBy];
    if (fieldName) {
        if (orderBy.length && orderBy[0].name === fieldName) {
            if (!needsReordering) {
                if (orderBy[0].asc) {
                    orderBy[0] = { name: orderBy[0].name, asc: false };
                } else {
                    orderBy = [...resetOrderBy];
                }
            }
        } else {
            orderBy = orderBy.filter((o) => o.name !== fieldName);
            orderBy.unshift({
                name: fieldName,
                asc: true,
            });
        }
    }
    return orderBy;
}

/**
 * @param {Object} record
 * @param {string[]} [copyFields=[]]
 * @returns {Object}
 */
export function copyRecordData(record, copyFields = []) {
    const data = {};
    for (const [name, value] of Object.entries(record.data)) {
        if (
            ![...copyFields, "display_name"].includes(name) &&
            (record._isReadonly(name) || record._isInvisible(name)) &&
            !record._isRequired(name)
        ) {
            continue;
        }
        switch (record.fields[name].type) {
            case "many2many": {
                const list = record.data[name];
                data[name] = list.currentIds.map((id) => {
                    const cached = list._cache[id]
                        ? copyRecordData(list._cache[id])
                        : false;
                    return [x2ManyCommands.LINK, id, cached];
                });
                break;
            }
            case "many2one":
            case "many2one_reference":
            case "reference":
                data[name] = value && { ...value };
                break;
            case "one2many":
                break;
            default:
                data[name] = value;
        }
    }
    return data;
}

/**
 * The server returns created rows without saying which virtual id each came
 * from; the only available correspondence is creation order, which the id
 * sequence makes ascending. Rank the new ids and zip them against the CREATE
 * commands. A count mismatch means the mapping is not derivable — callers must
 * not guess.
 *
 * Equal counts alone are NOT identity: a `create()` override may drop our row
 * and insert one of its own, and the zip would then graft our edited datapoint
 * onto a record we never created (every later update writing to the wrong
 * server row). When the caller can say where its rows sit, pass `positions`:
 * each virtual id's index in `clientIds` must equal its paired new id's index
 * in `serverIds`, or the mapping is refused — same fail-closed null as the
 * count mismatch, so callers drop the virtual row and heal from the server.
 *
 * @param {(number|string)[]} createVirtualIds
 * @param {number[]} newResIds
 * @param {{ clientIds: (number|string)[], serverIds: number[] }} [positions]
 *   the full ordered memberships: `clientIds` as the client last knew them
 *   (virtual ids included), `serverIds` as the server reported them post-save
 * @returns {Map<number|string, number> | null}
 */
export function pairCreatedRows(createVirtualIds, newResIds, positions) {
    if (newResIds.length !== createVirtualIds.length) {
        return null;
    }
    const ranked = [...newResIds].sort((x, y) => x - y);
    const pairs = new Map(
        createVirtualIds.map((virtualId, index) => [virtualId, ranked[index]]),
    );
    if (positions) {
        const { clientIds, serverIds } = positions;
        for (const [virtualId, resId] of pairs) {
            if (clientIds.indexOf(virtualId) !== serverIds.indexOf(resId)) {
                return null;
            }
        }
    }
    return pairs;
}
