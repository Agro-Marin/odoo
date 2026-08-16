// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/format/strings */

import { isObject } from "@web/core/utils/collections/objects";

/**
 * @template [T=unknown]
 * @typedef {[Record<string, T>] | T[]} Substitutions
 */

/**
 * @param {Substitutions} substitutions
 * @returns {boolean}
 */
function hasSubstitutionDict(substitutions) {
    return substitutions.length === 1 && isObject(substitutions[0]);
}

const HTML_ESCAPED_CHARACTERS = [
    ["&", "&amp;"],
    ["<", "&lt;"],
    [">", "&gt;"],
    ["'", "&#x27;"],
    ['"', "&quot;"],
    ["`", "&#x60;"],
];

const R_EMAIL =
    /^(([^<>()[\].,;:\s@"]+(\.[^<>()[\].,;:\s@"]+)*)|(".+"))@(([^<>()[\].,;:\s@"]+\.)+[^<>()[\].,;:\s@"]{2,})$/i;
const R_FALSY = /^(false|0)$/i;
const R_KEYED_SUBSTITUTION = /%\((?<key>[^)]+)\)s/g;
const R_NUMERIC = /^\d+$/;
const R_REGEX_SPECIAL_CHARS = /[.*+?^${}()|[\]\\]/g;

export const nbsp = "\u00a0";

/**
 * @param {string} str
 * @returns {string}
 */
export function capitalize(str) {
    return str ? str[0].toUpperCase() + str.slice(1) : "";
}

/**
 * @param {unknown} [value]
 * @returns {string}
 */
export function escape(value) {
    const str = typeof value === "string" ? value : String(value ?? "");
    return str.replace(_HTML_ESCAPE_RE, (ch) => _HTML_ESCAPE_MAP[ch]);
}
const _HTML_ESCAPE_MAP = Object.fromEntries(HTML_ESCAPED_CHARACTERS);
const _HTML_ESCAPE_RE = /[&<>'"`]/g;

/**
 * @param {string} pattern
 * @returns {string}
 */
export function escapeRegExp(pattern) {
    return pattern.replaceAll(R_REGEX_SPECIAL_CHARS, "\\$&");
}

/**
 * @param {string | null | undefined} str
 * @param {boolean} [trueIfEmpty=false]
 * @returns {boolean}
 */
export function exprToBoolean(str, trueIfEmpty = false) {
    return str ? !R_FALSY.test(str) : trueIfEmpty;
}

/**
 * @param {...string} strings
 * @returns {string}
 */
export function hashCode(...strings) {
    const str = strings.join("\x1C");

    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = (hash << 5) - hash + str.charCodeAt(i);
        hash |= 0;
    }

    return (hash + _HEX_8).toString(16).slice(-8);
}
const _HEX_8 = 16 ** 8;

/**
 * 53-bit hash: collision-safe enough to key caches whose entries must not be
 * confused with one another.
 *
 * @param {string} str
 * @returns {number}
 */
export function cyrb53(str) {
    let h1 = 0xdeadbeef;
    let h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) {
        const ch = str.charCodeAt(i);
        h1 = Math.imul(h1 ^ ch, 2654435761);
        h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
    h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
    h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return 4294967296 * (2097151 & h2) + (h1 >>> 0);
}

/**
 * @param {string} str
 * @param {number[]} indices
 * @param {string | false} [separator=""]
 * @returns {string}
 */
export function intersperse(str, indices, separator) {
    /** @type {string[]} */
    const result = [];
    let last = str.length;
    for (let i = 0; i < indices.length; ++i) {
        let section = indices[i];
        if (section === -1 || last <= 0) {
            break;
        } else if (section === 0 && i === 0) {
            break;
        } else if (section === 0) {
            section = indices[--i];
        }
        const start = Math.max(0, last - section);
        result.push(str.slice(start, last));
        last -= section;
    }
    if (last > 0) {
        result.push(str.slice(0, last));
    }
    result.reverse();
    return result.join(separator || "");
}

/**
 * @param {string} value
 * @returns {boolean}
 */
export function isEmail(value) {
    return R_EMAIL.test(value);
}

/**
 * @param {string} value
 * @returns {boolean}
 */
export function isNumeric(value) {
    return R_NUMERIC.test(value);
}

/**
 * @template T, M
 * @param {Substitutions<T>} substitutions
 * @param {(value: T) => M} mapFn
 * @returns {Substitutions<M>}
 */
export function mapSubstitutions(substitutions, mapFn) {
    if (hasSubstitutionDict(substitutions)) {
        /** @type {{[key: string]: M}} */
        const substitutionDict = {};
        for (const [key, value] of Object.entries(
            /** @type {any} */ (substitutions[0]),
        )) {
            substitutionDict[key] = mapFn(value);
        }
        return /** @type {Substitutions<M>} */ ([substitutionDict]);
    } else {
        return /** @type {Substitutions<M>} */ (
            /** @type {any[]} */ (substitutions).map(mapFn)
        );
    }
}

/**
 * @template T
 * @param {string} str
 * @param {Substitutions<T>} substitutions
 * @returns {string}
 */
export function sprintf(str, ...substitutions) {
    if (!substitutions.length) {
        return str;
    }
    if (hasSubstitutionDict(substitutions)) {
        const dict = /** @type {Record<string, any>} */ (substitutions[0]);
        return str.replaceAll(R_KEYED_SUBSTITUTION, (_match, key) => dict[key] ?? "");
    } else {
        const raw = [""];
        for (let i = 0; i < str.length; i++) {
            if (str[i] === "%") {
                if (str[i + 1] === "%") {
                    raw[raw.length - 1] += str[++i];
                    continue;
                }
                if (str[i + 1] === "s") {
                    i++;
                    raw.push("");
                    continue;
                }
            }
            raw[raw.length - 1] += str[i];
        }
        const padded =
            substitutions.length >= raw.length - 1
                ? substitutions
                : [
                      ...substitutions,
                      ...Array(raw.length - 1 - substitutions.length).fill(""),
                  ];
        return String.raw({ raw }, ...padded);
    }
}

/**
 * 16 lowercase hex characters — 64 random bits, no dashes. Despite the name
 * this is not an RFC 4122 UUID and never has been; `crypto.randomUUID()` is
 * what you want if a caller needs that shape. Documented because callers have
 * assumed otherwise (one stripped a dash that is never produced).
 *
 * @returns {string}
 */
export function uuid() {
    let id = "";
    for (const b of crypto.getRandomValues(new Uint8Array(8))) {
        id += b.toString(16).padStart(2, "0");
    }
    return id;
}
