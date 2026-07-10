// @ts-check
/** @odoo-module native */

/** @module @web/views/field_arch - Parses an XML `<field>` arch node into a normalized fieldInfo object */

/**
 * View-arch parsing for `<field>` nodes.
 *
 * Extracted from {@link Field} (`@web/fields/field`) so arch parsing —
 * a view-layer concern — isn't coupled to the rendering component's registry
 * lookups and render-time setup.
 *
 * Recursively dispatches to view-type ArchParsers
 * (`registry.category("views").get(viewType).ArchParser`) for x2many
 * sub-views; living under `@web/views/` makes that a same-layer reference
 * instead of a back-edge from fields → views.
 */

import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { getFieldFromRegistry } from "@web/fields/field";
import { X2M_TYPES } from "@web/fields/field_types";
import { utils } from "@web/ui/block/ui_service";

const isSmall = utils.isSmall;
const viewRegistry = registry.category("views");

/**
 * Parses an XML `<field>` node from a view arch into a normalized
 * fieldInfo object, resolving widget, options, decorations, x2many
 * sub-views, and related fields.
 *
 * @param {Element} node - XML `<field>` element from the view arch
 * @param {Record<string, { fields: Record<string, { type: string, string?: string, relation?: string, readonly?: boolean, [k: string]: any }> }>} models - Model metadata keyed by model name
 * @param {string} modelName - Technical model name (e.g. "res.partner")
 * @param {string} viewType - View type (e.g. "list", "form", "kanban")
 * @param {string} [jsClass] - JS class prefix for compound registry lookup
 * @returns {{ name: string, type: string, viewType: string, widget: string | null, field: ReturnType<typeof getFieldFromRegistry>, context: string, string?: string, help?: string, onChange: boolean, forceSave: boolean, options: Object, decorations: Record<string, string>, attrs: Record<string, string>, domain?: string, readonly?: string | null, required?: string | null, invisible?: string | null, column_invisible?: string | null, viewMode?: string, views?: Object, relatedFields?: Object, isHandle?: boolean }}
 */
export function parseFieldNode(node, models, modelName, viewType, jsClass) {
    // A `<field>` node always carries a name; the throw below guards the rest.
    const name = /** @type {string} */ (node.getAttribute("name"));
    const widget = node.getAttribute("widget");
    const fields = models[modelName].fields;
    if (!fields[name]) {
        throw new Error(`"${modelName}"."${name}" field is undefined.`);
    }
    const field = getFieldFromRegistry(
        fields[name].type,
        widget ?? undefined,
        viewType,
        jsClass,
    );
    const fieldInfo = {
        name,
        type: fields[name].type,
        viewType,
        widget,
        field,
        context: "{}",
        string: fields[name].string,
        help: undefined,
        onChange: false,
        forceSave: false,
        options: {},
        decorations: {},
        attrs: {},
        domain: undefined,
    };

    for (const attr of ["invisible", "column_invisible", "readonly", "required"]) {
        fieldInfo[attr] = node.getAttribute(attr);
        if (fieldInfo[attr] === "True") {
            if (attr === "column_invisible") {
                fieldInfo.invisible = "True";
            }
        } else if (fieldInfo[attr] === null && fields[name][attr]) {
            fieldInfo[attr] = "True";
        }
    }

    for (const { name, value } of node.attributes) {
        if (["name", "widget"].includes(name)) {
            // avoid adding name and widget to attrs
            continue;
        }
        if (["context", "string", "help", "domain"].includes(name)) {
            fieldInfo[name] = value;
        } else if (name === "on_change") {
            fieldInfo.onChange = exprToBoolean(value);
        } else if (name === "options") {
            fieldInfo.options = evaluateExpr(value);
        } else if (name === "force_save") {
            fieldInfo.forceSave = exprToBoolean(value);
        } else if (name.startsWith("decoration-")) {
            fieldInfo.decorations[name.replace("decoration-", "")] = value;
        } else if (!name.startsWith("t-att")) {
            // all other (non dynamic) attributes
            fieldInfo.attrs[name] = value;
        }
    }
    if (name === "id") {
        fieldInfo.readonly = "True";
    }

    if (widget === "handle") {
        fieldInfo.isHandle = true;
    }

    if (X2M_TYPES.includes(fields[name].type)) {
        const views = {};
        let relatedFields = fieldInfo.field.relatedFields;
        if (relatedFields) {
            if (relatedFields instanceof Function) {
                relatedFields = relatedFields(fieldInfo);
            }
            const relatedFieldsArr = /** @type {any[]} */ (relatedFields);
            for (const relatedField of relatedFieldsArr) {
                if (!("readonly" in relatedField)) {
                    relatedField.readonly = true;
                }
            }
            relatedFields = Object.fromEntries(
                relatedFieldsArr.map((f) => [f.name, f]),
            );
            views.default = {
                fieldNodes: relatedFields,
                fields: relatedFields,
            };
            if (!fieldInfo.field.useSubView) {
                fieldInfo.viewMode = "default";
            }
        }
        for (const child of node.children) {
            const viewType = child.tagName;
            // ``viewRegistry`` entries carry ``ArchParser`` on the descriptor
            // object; cast the lookup so the destructure typechecks without
            // a ``/** @type {any} */`` escape on the call. The runtime
            // shape is enforced by the views-registry validator.
            const { ArchParser } =
                /** @type {{ ArchParser: new () => { parse: (n: Element, m: any, r?: string) => any } }} */ (
                    viewRegistry.get(viewType)
                );
            // We copy and hence isolate the subview from the main view's tree
            // This way, the subview's tree is autonomous and CSS selectors will work normally
            const childCopy = /** @type {Element} */ (child.cloneNode(true));
            const archInfo = new ArchParser().parse(
                childCopy,
                models,
                fields[name].relation,
            );
            views[viewType] = {
                ...archInfo,
                limit: archInfo.limit || 40,
                fields: models[/** @type {string} */ (fields[name].relation)].fields,
            };
        }

        let viewMode = node.getAttribute("mode");
        if (viewMode) {
            if (viewMode.split(",").length !== 1) {
                viewMode = isSmall() ? "kanban" : "list";
            }
        } else {
            if (views.list && !views.kanban) {
                viewMode = "list";
            } else if (!views.list && views.kanban) {
                viewMode = "kanban";
            } else if (views.list && views.kanban) {
                viewMode = isSmall() ? "kanban" : "list";
            }
        }
        if (viewMode) {
            fieldInfo.viewMode = viewMode;
        }
        if (Object.keys(views).length) {
            fieldInfo.relatedFields =
                models[/** @type {string} */ (fields[name].relation)]?.fields;
            fieldInfo.views = views;
        }
    }
    if (["many2one", "many2one_reference"].includes(fields[name].type)) {
        /** @type {any} */
        let relatedFields = fieldInfo.field.relatedFields;
        if (relatedFields) {
            relatedFields = Object.fromEntries(relatedFields.map((f) => [f.name, f]));
            fieldInfo.viewMode = "default";
            fieldInfo.views = {
                default: {
                    fieldNodes: relatedFields,
                    fields: relatedFields,
                },
            };
        }
    }

    return fieldInfo;
}
