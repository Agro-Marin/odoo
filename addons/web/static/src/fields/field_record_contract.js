// @ts-check
/** @odoo-module native */

/**
 * @type {string[]}
 */
export const FIELD_RECORD_SURFACE = [
    "data",
    "savedData",
    "update",
    "fields",
    "fieldNames",
    "resId",
    "resModel",
    "id",
    "isNew",
    "context",
    "evalContext",
    "evalContextWithVirtualIds",
    "dirty",
    "isInEdition",
    "isActive",
    "isValid",
    "isFieldInvalid",
    "activeFields",
    "setInvalidField",
    "resetFieldValidity",
    "save",
    "discard",
    "load",
    "model",
];

/**
 * @type {string[]}
 */
export const FIELD_OWN_VALUE_SURFACE = ["data", "update", "fields"];

/**
 * @typedef {{
 * data: Record<string, any>,
 * update: (changes: Record<string, any>, options?: { save?: boolean }) => Promise<void>,
 * fields: Record<string, any>,
 * }} FieldOwnValueContract
 */
