// @ts-check
/** @odoo-module native */

import { serializeDate, serializeDateTime } from "@web/core/l10n/dates";
import { DateTime } from "@web/core/l10n/luxon";

import {
    DATE_DELTA,
    DESCRIPTION_REGEX,
    EMAIL_REGEX,
    FLOAT_PRECISION,
    getSampleFromId,
    MAX_COLOR_INT,
    MAX_FLOAT,
    MAX_INTEGER,
    MAX_MONETARY,
    PEOPLE_MODELS,
    PHONE_REGEX,
    SAMPLE_COUNTRIES,
    SAMPLE_PEOPLE,
    SAMPLE_TEXTS,
    SUB_RECORDSET_SIZE,
    URL_REGEX,
} from "./sample_data.js";

/** @param {any[]} array */
export function getRandomArrayEl(array) {
    return array[Math.floor(Math.random() * array.length)];
}

/** @returns {boolean} */
export function getRandomBool() {
    return Math.random() < 0.5;
}

/** @returns {any} */
function getRandomDate() {
    const delta = Math.floor((Math.random() - Math.random()) * DATE_DELTA);
    return DateTime.local().plus({ hours: delta });
}

/**
 * @param {number} max
 * @returns {number}
 */
function getRandomFloat(max) {
    return sanitizeNumber(Math.random() * max);
}

/**
 * @param {number} max
 * @returns {number}
 */
export function getRandomInt(max) {
    return Math.floor(Math.random() * max);
}

/** @returns {number} */
export function getRandomSubRecordId() {
    return Math.floor(Math.random() * SUB_RECORDSET_SIZE) + 1;
}

/**
 * @param {number} value
 * @returns {number}
 */
export function sanitizeNumber(value) {
    return parseFloat(value.toFixed(FLOAT_PRECISION));
}

/**
 * @typedef {{
 * getRandomBool?: () => boolean;
 * getRandomSubRecordId?: () => number;
 * getRandomArrayEl?: <T>(array: T[]) => T;
 * }} FieldGeneratorHooks
 */

/**
 * @param {string} modelName
 * @param {string} fieldName
 * @param {Record<string, any>} field
 * @param {number} id
 * @param {FieldGeneratorHooks} [hooks]
 * @returns {any}
 */
export function generateFieldValue(modelName, fieldName, field, id, hooks = {}) {
    const _getRandomBool = hooks.getRandomBool ?? getRandomBool;
    const _getRandomSubRecordId = hooks.getRandomSubRecordId ?? getRandomSubRecordId;
    const _getRandomArrayEl = hooks.getRandomArrayEl ?? getRandomArrayEl;

    switch (field.type) {
        case "boolean":
            return fieldName === "active" ? true : _getRandomBool();
        case "char":
        case "text":
            return _generateTextValue(modelName, fieldName, id);
        case "date":
        case "datetime": {
            const datetime = getRandomDate();
            return field.type === "date"
                ? serializeDate(datetime)
                : serializeDateTime(datetime);
        }
        case "float":
            return getRandomFloat(MAX_FLOAT);
        case "integer": {
            let max = MAX_INTEGER;
            if (fieldName.includes("color")) {
                max = _getRandomBool() ? MAX_COLOR_INT : 0;
            }
            return getRandomInt(max);
        }
        case "monetary":
            return getRandomInt(MAX_MONETARY);
        case "many2one":
            if (field.relation === "res.currency") {
                return 1;
            }
            if (field.relation === "ir.attachment") {
                return false;
            }
            return _getRandomSubRecordId();
        case "one2many":
        case "many2many": {
            const ids = [_getRandomSubRecordId(), _getRandomSubRecordId()];
            return [...new Set(ids)];
        }
        case "selection":
            if (field.selection?.length > 0) {
                return _getRandomArrayEl(field.selection)[0];
            }
            return false;
        default:
            return false;
    }
}

/**
 * @param {string} modelName
 * @param {string} fieldName
 * @param {number} id
 * @returns {string | false}
 */
function _generateTextValue(modelName, fieldName, id) {
    if (["display_name", "name"].includes(fieldName)) {
        if (PEOPLE_MODELS.includes(modelName)) {
            return getSampleFromId(id, SAMPLE_PEOPLE);
        } else if (modelName === "res.country") {
            return getSampleFromId(id, SAMPLE_COUNTRIES);
        }
    }
    if (fieldName === "display_name") {
        return getSampleFromId(id, SAMPLE_TEXTS);
    } else if (["name", "reference"].includes(fieldName)) {
        return `REF${String(id).padStart(4, "0")}`;
    } else if (DESCRIPTION_REGEX.test(fieldName)) {
        return getSampleFromId(id, SAMPLE_TEXTS);
    } else if (EMAIL_REGEX.test(fieldName)) {
        const emailName = getSampleFromId(id, SAMPLE_PEOPLE)
            .replace(/ /, ".")
            .toLowerCase();
        return `${emailName}@sample.demo`;
    } else if (PHONE_REGEX.test(fieldName)) {
        return `+1 555 754 ${String(id).padStart(4, "0")}`;
    } else if (URL_REGEX.test(fieldName)) {
        return `http://sample${id}.com`;
    }
    return false;
}
