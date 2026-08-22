// @ts-check
/** @odoo-module native */

import "@web/core/formatters";
import "@web/core/parsers";

import { registry } from "@web/core/registry";

/**
 * @typedef {object} FieldCodec
 * @property {(value: any, options?: Record<string, any>) => string} format
 * @property {(value: string, options?: Record<string, any>) => any} parse
 * @property {(fieldInfo: any) => Record<string, any>} extractOptions
 * @property {(value: any, field?: any) => any} deserialize
 * @property {(value: any) => any} serialize
 * @property {boolean} parseable
 */

const formatters = registry.category("formatters");
const parsers = registry.category("parsers");
const serializers = registry.category("serializers");
const deserializers = registry.category("deserializers");

const TEXT_TYPES = new Set(["char", "text", "html"]);

/**
 * @param {unknown} value
 */
const formatUnknown = (value) =>
    value == null || value === false ? "" : String(value);

/**
 * @type {Map<string, FieldCodec>}
 */
const codecCache = new Map();

/**
 * @param {string} type
 * @returns {FieldCodec}
 */
export function getFieldCodec(type) {
    const cached = codecCache.get(type);
    if (cached) {
        return cached;
    }
    /** @type {FieldCodec} */
    const codec = {
        format: (value, options) => formatters.get(type, formatUnknown)(value, options),
        parse: (value, options) =>
            parsers.contains(type) ? parsers.get(type)(value, options) : value,
        extractOptions: (fieldInfo) => {
            const fn = /** @type {any} */ (formatters.get(type, formatUnknown));
            return fn.extractOptions ? fn.extractOptions(fieldInfo) : {};
        },
        deserialize: (value, field) =>
            deserializers.get(type, (v) => v)(value, field ?? { type }),
        serialize: (value) => serializers.get(type, (v) => v)(value),
        get parseable() {
            return parsers.contains(type) || TEXT_TYPES.has(type);
        },
    };
    codecCache.set(type, codec);
    return codec;
}

/**
 * @param {string} type
 * @returns {boolean}
 */
export function hasFieldCodec(type) {
    return formatters.contains(type);
}
