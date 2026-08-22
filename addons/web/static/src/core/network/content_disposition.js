// @ts-check
/** @odoo-module native */

/* eslint-disable */


/**
 * @private
 */
const HEX_ESCAPE_REPLACE_REGEXP = /%([0-9A-Fa-f]{2})/g;

/**
 * @private
 */
const NON_LATIN1_REGEXP = /[^\x20-\x7e\xa0-\xff]/g;

/**
 * @private
 */
const QESC_REGEXP = /\\([\u0000-\u007f])/g;

/**
 * @private
 */
const PARAM_REGEXP = /;[\x09\x20]*([!#$%&'*+.0-9A-Z^_`a-z|~-]+)[\x09\x20]*=[\x09\x20]*("(?:[\x09\x20!\x23-\x5b\x5d-\x7e\x80-\xff]|\\[\x20-\x7e])*"|[!#$%&'*+.0-9A-Z^_`a-z|~-]+)[\x09\x20]*/g;

/**
 * @private
 */
const EXT_VALUE_REGEXP = /^([A-Za-z0-9!#$%&+\-^_`{}~]+)'(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4,8}|)'((?:%[0-9A-Fa-f]{2}|[A-Za-z0-9!#$&+.^_`|~-])+)$/;

/**
 * @private
 */
const DISPOSITION_TYPE_REGEXP = /^([!#$%&'*+.0-9A-Z^_`a-z|~-]+)[\x09\x20]*(?:$|;)/;

/**
 * @param {string} str
 * @return {string}
 * @private
 */
function decodefield(str) {
    const match = EXT_VALUE_REGEXP.exec(str);

    if (!match) {
        throw new TypeError("invalid extended field value");
    }

    const charset = match[1].toLowerCase();
    const encoded = match[2];

    switch (charset) {
        case "iso-8859-1":
            return encoded
                .replace(HEX_ESCAPE_REPLACE_REGEXP, pdecode)
                .replace(NON_LATIN1_REGEXP, "?");
        case "utf-8":
            return decodeURIComponent(encoded);
        default:
            throw new TypeError("unsupported charset in extended field");
    }
}

/**
 * @param {string} string
 * @return {ContentDisposition}
 * @public
 */
export function parse(string) {
    if (!string || typeof string !== "string") {
        throw new TypeError("argument string is required");
    }

    let match = DISPOSITION_TYPE_REGEXP.exec(string);

    if (!match) {
        throw new TypeError("invalid type format");
    }

    let index = match[0].length;
    const type = match[1].toLowerCase();

    let key;
    /** @type {string[]} */
    const names = [];
    /** @type {Record<string, string>} */
    const params = {};
    let value;

    index = PARAM_REGEXP.lastIndex = match[0].at(-1) === ";" ? index - 1 : index;

    while ((match = PARAM_REGEXP.exec(string))) {
        if (match.index !== index) {
            throw new TypeError("invalid parameter format");
        }

        index += match[0].length;
        key = match[1].toLowerCase();
        value = match[2];

        if (names.includes(key)) {
            throw new TypeError("invalid duplicate parameter");
        }

        names.push(key);

        if (key.indexOf("*") + 1 === key.length) {
            key = key.slice(0, -1);
            value = decodefield(value);

            params[key] = value;
            continue;
        }

        if (typeof params[key] === "string") {
            continue;
        }

        if (value[0] === '"') {
            value = value.slice(1, -1).replace(QESC_REGEXP, "$1");
        }

        params[key] = value;
    }

    if (index !== -1 && index !== string.length) {
        throw new TypeError("invalid parameter format");
    }

    return new ContentDisposition(type, params);
}

/**
 * @param {string} str
 * @param {string} hex
 * @return {string}
 * @private
 */
function pdecode(str, hex) {
    return String.fromCharCode(Number.parseInt(hex, 16));
}

/**
 * @public
 * @param {string} type
 * @param {Record<string, string>} parameters
 * @constructor
 */
function ContentDisposition(type, parameters) {
    this.type = type;
    this.parameters = parameters;
}
/* eslint-enable */
