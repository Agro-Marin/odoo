// @ts-check
/** @odoo-module native */

/** @module @web/fields/dynamic_placeholder_syntax */

/**
 * The one place that knows what a dynamic placeholder looks like.
 *
 * Two widgets write placeholders -- `useDynamicPlaceholder` into char/text
 * fields as `{{ expr ||| default }}`, and the html_editor plugin into html
 * fields as `<t t-out="expr">default</t>` -- and one server-side pair reads
 * them back (`parse_inline_template`, `ir.qweb`). While each widget composed
 * its own string the two disagreed on everything that was not the bare path:
 * a datetime came out localised in a body and as a raw UTC timestamp with
 * microseconds in a subject, and a default value containing `}}` terminated
 * the inline placeholder early and leaked the rest of itself into the mail.
 *
 * Both widgets now compose through here, so a rule is stated once.
 */

/**
 * Field types no placeholder can render to anything a reader wants.
 *
 * `binary` renders as the Python `repr` of the bytes -- `b'iVBORw0KGgo...'`,
 * the whole base64 payload -- straight into a subject line. `boolean` renders
 * as `True`/`False`, untranslated. The x2many types have no scalar form.
 */
export const UNRENDERABLE_FIELD_TYPES = [
    "binary",
    "boolean",
    "one2many",
    "many2many",
    "json",
    "properties_definition",
];

/**
 * Additionally unrenderable when the placeholder lands in a plain-text field.
 *
 * An html source in a `Subject:` reaches the recipient as literal tags: the
 * inline engine stringifies `Markup` exactly like `str`.
 */
export const RICH_TEXT_FIELD_TYPES = ["html"];

/**
 * @param {Object} fieldDef
 * @param {Object} [options]
 * @param {boolean} [options.plainText] the placeholder targets a char/text field
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
 * The expression a placeholder for `path` will carry.
 *
 * This is what the server judges -- `ir_qweb._is_expression_allowed` tests the
 * *expression*, not the path -- so the picker must filter on the return value
 * of this function rather than on `object.<path>`, or it offers fields whose
 * placeholder the server will then refuse.
 *
 * @param {string} path
 * @param {Object} [options]
 * @param {string} [options.fieldType]
 * @param {string} [options.tzPath] partner field whose `tz` localises a datetime
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
 * Resolve the partner field whose timezone localises a datetime, or null.
 *
 * @param {Object} orm
 * @param {string} resModel
 * @returns {Promise<string | null>}
 */
export async function resolveTzPath(orm, resModel) {
    if (!resModel) {
        return null;
    }
    const partnerFields = await orm.call(resModel, "mail_get_partner_fields", [[]]);
    return partnerFields.length ? partnerFields[0] : null;
}

/**
 * Escape a default value for the `{{ expr ||| default }}` grammar.
 *
 * `}}` ends a placeholder, so a default containing one used to truncate the
 * placeholder and spill its tail into the rendered text. `parse_inline_template`
 * accepts `\}` and `\\` in the default clause and unescapes them; nothing else
 * is escaped, so a default that only holds a stray backslash is left as typed.
 *
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
 * `{{ expr ||| default }}`, for a char or text field.
 *
 * @param {PlaceholderSpec} spec
 * @returns {string}
 */
export function buildInlinePlaceholder({ path, fieldType, defaultValue, tzPath }) {
    const expression = placeholderExpression(path, { fieldType, tzPath });
    const fallback = defaultValue ? ` ||| ${escapeInlineDefault(defaultValue)}` : "";
    return `{{${expression}${fallback}}}`;
}

/**
 * The expression and body of a `<t t-out="expr">default</t>`, for an html field.
 *
 * Returned as data rather than as an element so that this module stays free of
 * the DOM and can be exercised without one.
 *
 * @param {PlaceholderSpec} spec
 * @returns {{expression: string, body: string}}
 */
export function buildQwebPlaceholder({ path, fieldType, defaultValue, tzPath }) {
    return {
        expression: placeholderExpression(path, { fieldType, tzPath }),
        body: defaultValue || "",
    };
}
