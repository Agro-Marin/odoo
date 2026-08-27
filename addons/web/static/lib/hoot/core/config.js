/** @odoo-module */

import { DEFAULT_EVENT_TYPES } from "../hoot_utils.js";
import { generateSeed } from "../mock/math.js";

/**
 * @typedef {keyof typeof FILTER_SCHEMA} SearchFilter
 */

const {
    Number: { parseFloat: $parseFloat },
    Object: { entries: $entries, fromEntries: $fromEntries, keys: $keys },
} = globalThis;

/**
 * @template {Record<string, any>} T
 * @param {T} schema
 * @returns {{ [key in keyof T]: ReturnType<T[key]["parse"]> }}
 */
function getSchemaDefaults(schema) {
    return $fromEntries($entries(schema).map(([key, value]) => [key, value.default]));
}

/**
 * @template {Record<string, any>} T
 * @param {T} schema
 * @returns {(keyof T)[]}
 */
function getSchemaKeys(schema) {
    return $keys(schema);
}

/**
 * @template T
 * @param {(values: string[]) => T} parse
 * @returns {(valueIfEmpty: T) => (values: string[]) => T}
 */
function makeParser(parse) {
    return (valueIfEmpty) => (values) => (values.length ? parse(values) : valueIfEmpty);
}

const parseBoolean = makeParser(([value]) => value === "true");

const parseNumber = makeParser(([value]) => $parseFloat(value) || 0);

/** @type {ReturnType<typeof makeParser<"first-fail" | "failed" | false>>} */
const parseShowDetail = makeParser(([value]) => (value === "false" ? false : value));

const parseString = makeParser(([value]) => value);

const parseStringArray = makeParser((values) => values);

export const CONFIG_SCHEMA = {
    bail: {
        default: 0,
        parse: parseNumber(1),
    },
    debug: {
        default: "",
        parse: parseString("assets"),
    },
    debugTest: {
        default: false,
        parse: parseBoolean(true),
    },
    events: {
        default: DEFAULT_EVENT_TYPES,
        parse: parseNumber(0),
    },
    fps: {
        default: 60,
        parse: parseNumber(60),
    },
    fun: {
        default: false,
        parse: parseBoolean(true),
    },
    headless: {
        default: false,
        parse: parseBoolean(true),
    },
    hookTimeout: {
        default: 5_000,
        parse: parseNumber(5_000),
    },
    loglevel: {
        default: 0,
        parse: parseNumber(0),
    },
    manual: {
        default: false,
        parse: parseBoolean(true),
    },
    networkDelay: {
        default: "0",
        parse: parseString("0"),
    },
    notrycatch: {
        default: false,
        parse: parseBoolean(true),
    },
    order: {
        default: "fifo",
        parse: parseString(""),
    },
    preset: {
        default: "",
        parse: parseString(""),
    },
    random: {
        default: 0,
        parse: parseString(generateSeed()),
    },
    showdetail: {
        default: "first-fail",
        parse: parseShowDetail("failed"),
    },
    timeout: {
        default: 5_000,
        parse: parseNumber(5_000),
    },
};

export const FILTER_SCHEMA = {
    filter: {
        aliases: ["name"],
        default: "",
        parse: parseString(""),
    },
    id: {
        aliases: ["ids"],
        default: [],
        parse: parseStringArray([]),
    },
    tag: {
        aliases: ["tags"],
        default: [],
        parse: parseStringArray([]),
    },
};

export const DEFAULT_CONFIG = getSchemaDefaults(CONFIG_SCHEMA);
export const CONFIG_KEYS = getSchemaKeys(CONFIG_SCHEMA);

export const DEFAULT_FILTERS = getSchemaDefaults(FILTER_SCHEMA);
export const FILTER_KEYS = getSchemaKeys(FILTER_SCHEMA);
