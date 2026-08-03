// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_value_utils */

/**
 * @param {string} gb
 * @param {Object} fields
 * @returns {string}
 */

import { _t } from "@web/core/translation";
function normalize(gb, fields) {
    const [fieldName, interval] = gb.split(":");
    const field = fields[fieldName];
    if (field && ["date", "datetime"].includes(field.type)) {
        return `${fieldName}:${interval || "month"}`;
    }
    return fieldName;
}

/**
 * @param {any} value
 * @returns {any}
 */
function sanitizeValue(value) {
    if (Array.isArray(value)) {
        return value[0];
    }
    return value;
}

/**
 * @param {any} value
 * @param {string} groupBy
 * @param {Object} config
 * @returns {string}
 */
function sanitizeLabel(value, groupBy, config) {
    const { metaData } = config;
    const fieldName = groupBy.split(":")[0];
    if (fieldName && metaData.fields[fieldName]) {
        const field = metaData.fields[fieldName];
        if (field.type === "boolean") {
            return value === undefined ? _t("None") : value ? _t("Yes") : _t("No");
        } else if (field.type === "integer") {
            if (fieldName === "id" && Array.isArray(value)) {
                return value[1];
            }
            return value || "0";
        }
    }
    if (value === false) {
        return metaData.fields[fieldName]?.falsy_value_label || _t("None");
    }
    if (Array.isArray(value)) {
        return getNumberedLabel(value, fieldName, config);
    }
    if (
        fieldName &&
        metaData.fields[fieldName] &&
        metaData.fields[fieldName].type === "selection"
    ) {
        const selected = metaData.fields[fieldName].selection.find(
            (o) => o[0] === value,
        );
        return selected ? selected[1] : value;
    }
    return value;
}

/**
 * @param {Array} label
 * @param {string} fieldName
 * @param {Object} config
 * @returns {string}
 */
function getNumberedLabel(label, fieldName, config) {
    const { data } = config;
    const id = label[0];
    const name = label[1];
    data.numbering[fieldName] = data.numbering[fieldName] || {};
    data.numbering[fieldName][name] = data.numbering[fieldName][name] || {};
    const numbers = data.numbering[fieldName][name];
    numbers[id] = numbers[id] || Object.keys(numbers).length + 1;
    return numbers[id] > 1 ? `${name}  (${numbers[id]})` : name;
}

/**
 * @param {Object} group
 * @param {string[]} groupBys
 * @param {Object} config
 * @param {Object} fields
 * @returns {string[]}
 */
export function getGroupLabels(group, groupBys, config, fields) {
    return groupBys.map((gb) => {
        const groupBy = normalize(gb, fields);
        return sanitizeLabel(group[groupBy], groupBy, config);
    });
}

/**
 * @param {Object} group
 * @param {string[]} groupBys
 * @param {Object} fields
 * @returns {Array}
 */
export function getGroupValues(group, groupBys, fields) {
    return groupBys.map((gb) => {
        const groupBy = normalize(gb, fields);
        return sanitizeValue(group[groupBy]);
    });
}

/**
 * @param {string[]} rowGroupBy
 * @param {string[]} colGroupBy
 * @param {Object} fields
 * @returns {string[]}
 */
export function getGroupBySpecs(rowGroupBy, colGroupBy, fields) {
    const set = [...rowGroupBy, ...colGroupBy].reduce((acc, gb) => {
        acc.add(normalize(gb, fields));
        return acc;
    }, new Set());
    return [...set];
}

/**
 * @param {Object} group
 * @param {Object} config
 * @returns {Array[]}
 */
export function getGroupDomain(group, config) {
    const { data } = config;
    const key = JSON.stringify([group.rowValues, group.colValues]);
    return data.groupDomains[key];
}
