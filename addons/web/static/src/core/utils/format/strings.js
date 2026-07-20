// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/format/strings - String helpers: sprintf, escapeRegExp, email validation, intersperse */

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

/**
 * Based on:
 * {@link http://stackoverflow.com/questions/46155/validate-email-address-in-javascript}
 */
const R_EMAIL =
    /^(([^<>()[\].,;:\s@"]+(\.[^<>()[\].,;:\s@"]+)*)|(".+"))@(([^<>()[\].,;:\s@"]+\.)+[^<>()[\].,;:\s@"]{2,})$/i;
const R_FALSY = /^(false|0)$/i;
const R_KEYED_SUBSTITUTION = /%\((?<key>[^)]+)\)s/g;
const R_NUMERIC = /^\d+$/;
const R_REGEX_SPECIAL_CHARS = /[.*+?^${}()|[\]\\]/g;

export const nbsp = "\u00a0";

/**
 * Capitalizes a string: "abc def" => "Abc def"
 *
 * @param {string} str the input string
 * @returns {string}
 */
export function capitalize(str) {
    return str ? str[0].toUpperCase() + str.slice(1) : "";
}

/**
 * Escapes HTML special characters in a given value, returning a plain string.
 *
 * Escapes the SAME six characters as OWL's ``htmlEscape`` (re-exported as the
 * canonical markup-aware helper from ``@web/core/utils/dom/html``), but with
 * deliberately different trust semantics — so the two are NOT interchangeable:
 *
 *  - ``htmlEscape`` is Markup-aware: it passes a ``markup()`` value through
 *    UNESCAPED and returns Markup. Use it when composing safe HTML.
 *  - ``escape`` (this one) has NO passthrough: it coerces every input —
 *    including a String subclass / Markup / lazy ``_t`` string — to a plain
 *    string and always runs the replace (see the inline note below), returning
 *    an inert string. Use it where the result must never be treated as HTML.
 *
 * Prefer ``htmlEscape`` in markup-building contexts; keep ``escape`` where the
 * always-escape (no-trust) behavior is the point.
 *
 * @param {unknown} [value]
 * @returns {string}
 */
export function escape(value) {
    // Coerce first, THEN escape. A String subclass (e.g. a lazy translated
    // string from ``_t`` hoisted to module scope, or an OWL Markup object) is
    // ``typeof === "object"``, so a bare ``typeof value !== "string"`` guard
    // returned it stringified but UNESCAPED — a silent XSS footgun for a
    // primitive literally named ``escape``. Coercing to a plain string and
    // always running the replace closes that hole.
    const str = typeof value === "string" ? value : String(value ?? "");
    return str.replace(_HTML_ESCAPE_RE, (ch) => _HTML_ESCAPE_MAP[ch]);
}
const _HTML_ESCAPE_MAP = Object.fromEntries(HTML_ESCAPED_CHARACTERS);
const _HTML_ESCAPE_RE = /[&<>'"`]/g;

/**
 * Escapes a pattern to use as a RegExp.
 *
 * {@link https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Regular_expressions#escaping}
 *
 * @param {string} pattern
 * @returns {string} escaped string to use as a RegExp
 */
export function escapeRegExp(pattern) {
    return pattern.replaceAll(R_REGEX_SPECIAL_CHARS, "\\$&");
}

/**
 * Parses the string as a boolean: empty, "0", "False" or "false" are false;
 * everything else is true.
 *
 * @param {string | null | undefined} str
 * @param {boolean} [trueIfEmpty=false]
 * @returns {boolean}
 */
export function exprToBoolean(str, trueIfEmpty = false) {
    return str ? !R_FALSY.test(str) : trueIfEmpty;
}

/**
 * Generate a non-cryptographic hash (Java `String.hashCode()`-based) for the
 * given string(s). Not collision-resistant; use SubtleCrypto.digest() if a
 * cryptographic hash is needed.
 *
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

    // Convert the possibly negative number hash code into an 8 character
    // hexadecimal string
    return (hash + _HEX_8).toString(16).slice(-8);
}
const _HEX_8 = 16 ** 8;

/**
 * Intersperses ``separator`` in ``str`` at positions given by ``indices``,
 * relative offsets from the previous insertion point (starting at the end
 * of the string). Special values: ``-1`` stops insertion; ``0`` repeats the
 * previous section until ``str`` is consumed.
 *
 * @param {string} str
 * @param {number[]} indices
 * @param {string} [separator=""]
 * @returns {string}
 */
export function intersperse(str, indices, separator) {
    /** @type {string[]} */
    const result = [];
    let last = str.length;
    for (let i = 0; i < indices.length; ++i) {
        let section = indices[i];
        if (section === -1 || last <= 0) {
            // Done with string, or -1 (stops formatting string)
            break;
        } else if (section === 0 && i === 0) {
            // repeats previous section, which there is none => stop
            break;
        } else if (section === 0) {
            // repeat previous section forever
            //noinspection AssignmentToForLoopParameterJS
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
 * Return true if the string is composed of only digits
 *
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
 * Returns a string formatted using given values.
 *
 * If the value is an object:
 *  - its keys will replace `%(key)s` expressions;
 *  - these expressions CANNOT be escaped (e.g. '%%(key)s');
 *  - missing keys will yield empty strings.
 *
 * If the value(s) is a list of string(s):
 *  - they will replace `%s` expressions;
 *  - these expressions CAN be escaped by adding another '%';
 *  - surplus of "%s" expressions will be replaced by empty strings.
 *
 * If no value is given, the string will not be formatted at all.
 *
 * @template T
 * @param {string} str
 * @param {Substitutions<T>} substitutions
 * @returns {string}
 * @example
 *  // Generic substitutions
 *  sprintf("Hello %s!", "world"); // "Hello world!"
 *  sprintf("Hello %%s!", "world"); // "Hello %s!"
 *  // Keyed substitutions
 *  sprintf("Hello %(place)s!", { place: "world" }); // "Hello world!"
 *  sprintf("Hello %(missing)s!", { place: "world" }); // "Hello !"
 *  sprintf("Hello %%(place)s!", { place: "world" }); // "Hello %world!"
 *  // Unchanged because no substitutions
 *  sprintf("Hello %s!"); // "Hello %s!"
 */
export function sprintf(str, ...substitutions) {
    if (!substitutions.length) {
        // No substitutions => leave the string as is
        return str;
    }
    if (hasSubstitutionDict(substitutions)) {
        // Keyed (%(key)s) substitutions
        const dict = /** @type {Record<string, any>} */ (substitutions[0]);
        return str.replaceAll(R_KEYED_SUBSTITUTION, (_match, key) => dict[key] ?? "");
    } else {
        // Generic (%s) substitutions
        const raw = [""];
        for (let i = 0; i < str.length; i++) {
            if (str[i] === "%") {
                if (str[i + 1] === "%") {
                    // Escaped "%" character: => single "%"
                    raw[raw.length - 1] += str[++i];
                    continue;
                }
                if (str[i + 1] === "s") {
                    // Substitution (ignore "%s" in final string)
                    i++;
                    raw.push("");
                    continue;
                }
            }
            raw[raw.length - 1] += str[i];
        }
        // Pad substitutions to match the number of %s placeholders so that
        // excess %s tokens produce empty strings instead of literal "undefined".
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
 * Generate a unique identifier (64 bits) in hexadecimal.
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
