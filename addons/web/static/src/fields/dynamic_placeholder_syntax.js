// @ts-check
/** @odoo-module native */


export const UNRENDERABLE_FIELD_TYPES = [
    "binary",
    "boolean",
    "one2many",
    "many2many",
    "json",
    "properties_definition",
];

export const RICH_TEXT_FIELD_TYPES = ["html"];

/**
 * @param {Object} fieldDef
 * @param {Object} [options]
 * @param {boolean} [options.plainText]
 * @returns {boolean}
 */
export function isRenderableFieldType(fieldDef, { plainText = false } = {}) {
    if (UNRENDERABLE_FIELD_TYPES.includes(fieldDef.type)) {
        return false;
    }
    if (plainText && RICH_TEXT_FIELD_TYPES.includes(fieldDef.type)) {
        return false;
    }
    return !(fieldDef.is_property && fieldDef.type === "separator");
}

/**
 * @param {string} path
 * @param {Object} [options]
 * @param {string} [options.fieldType]
 * @param {string} [options.tzPath]
 * @returns {string}
 */
export function placeholderExpression(path, { fieldType, tzPath } = {}) {
    const value = `object.${path}`;
    switch (fieldType) {
        case "datetime":
            return tzPath
                ? `format_datetime(${value}, tz=object.${tzPath}.tz)`
                : `format_datetime(${value})`;
        case "date":
            return `format_date(${value})`;
        default:
            return value;
    }
}

/**
 * @param {Object} orm
 * @param {string} resModel
 * @returns {Promise<string | null>}
 */
export async function resolveTzPath(orm, resModel) {
    if (!resModel) {
        return null;
    }
    const partnerFields = await orm.call(resModel, "mail_get_partner_fields", []);
    return partnerFields.length ? partnerFields[0] : null;
}

/**
 * @param {string} text
 * @returns {string}
 */
export function escapeInlineDefault(text) {
    return text.replace(/[\\}]/g, "\\$&");
}

/**
 * @typedef {Object} PlaceholderSpec
 * @property {string} path
 * @property {string} [fieldType]
 * @property {string} [defaultValue]
 * @property {string} [tzPath]
 */

/**
 * @param {PlaceholderSpec} spec
 * @returns {string}
 */
export function buildInlinePlaceholder({ path, fieldType, defaultValue, tzPath }) {
    const expression = placeholderExpression(path, { fieldType, tzPath });
    const fallback = defaultValue ? ` ||| ${escapeInlineDefault(defaultValue)}` : "";
    return `{{${expression}${fallback}}}`;
}

/**
 * @param {PlaceholderSpec} spec
 * @returns {{expression: string, body: string}}
 */
export function buildQwebPlaceholder({ path, fieldType, defaultValue, tzPath }) {
    return {
        expression: placeholderExpression(path, { fieldType, tzPath }),
        body: defaultValue || "",
    };
}
