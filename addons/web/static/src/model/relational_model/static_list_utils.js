// @ts-check
/** @odoo-module native */

/**
 * @param {any} v1
 * @param {any} v2
 * @param {string} fieldType
 * @returns {boolean}
 */

import { x2ManyCommands } from "@web/core/network/commands";

/** @import { DatapointId } from "@web/model/types" */
/** @import { RelationalRecord } from "./record.js" */

/**
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
                    const cachedRecord = list._cache.get(id);
                    const cached = cachedRecord ? copyRecordData(cachedRecord) : false;
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
 * @param {(number|string)[]} createVirtualIds
 * @param {number[]} newResIds
 * @param {{ clientIds: (number|string)[], serverIds: number[] }} [positions]
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
