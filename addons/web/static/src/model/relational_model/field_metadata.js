// @ts-check
/** @odoo-module native */

/**
 * @param {boolean | string} value
 * @returns {string}
 */

import { isX2Many, isX2ManyType } from "@web/core/field_types";
import { omit } from "@web/core/utils/collections/objects";

import { invalidateAggregateSpecs } from "./field_values.js";
import {
    invalidateAllModifierDependencies,
    invalidateModifierDependencies,
} from "./record_utils.js";

/**
 * @param {boolean | string} value
 * @returns {string}
 */
function convertBoolToPyExpr(value) {
    if (value === true || value === false) {
        return value ? "True" : "False";
    }
    return value;
}

/**
 * `null` rides in from `combineModifiers`, which accepts it because its
 * dominant input is `Element.getAttribute`. It stops here: every one of these
 * reaches `convertBoolToPyExpr(x || false)`, so an absent modifier becomes
 * `"False"` however it was spelled.
 *
 * @typedef {{
 * context?: string;
 * invisible?: boolean | string | null;
 * readonly?: boolean | string | null;
 * required?: boolean | string | null;
 * onChange?: boolean | string;
 * forceSave?: boolean;
 * isHandle?: boolean;
 * }} ActiveFieldOptions
 */

export const FIELD_DEPENDENCIES_VALIDATION = {
    type: [
        Function,
        {
            type: Array,
            element: {
                type: Object,
                shape: {
                    name: String,
                    type: { type: String, optional: true },
                    optional: { type: Boolean, optional: true },
                    readonly: { type: [Boolean, String], optional: true },
                    written: { type: Boolean, optional: true },
                    "*": true,
                },
            },
        },
    ],
    optional: true,
};

export const RELATED_FIELDS_VALIDATION = {
    type: [
        Function,
        {
            type: Array,
            element: {
                type: Object,
                shape: {
                    name: String,
                    type: { type: String, optional: true },
                    relation: { type: String, optional: true },
                    readonly: { type: Boolean, optional: true },
                    selection: { type: Array, optional: true },
                    "*": true,
                },
            },
        },
    ],
    optional: true,
};

/**
 * @param {ActiveFieldOptions} [options]
 * @returns {Record<string, any>}
 */
export function makeActiveField({
    context,
    invisible,
    readonly,
    required,
    onChange,
    forceSave,
    isHandle,
} = {}) {
    return {
        context: context || "{}",
        invisible: convertBoolToPyExpr(invisible || false),
        readonly: convertBoolToPyExpr(readonly || false),
        required: convertBoolToPyExpr(required || false),
        onChange: onChange || false,
        forceSave: forceSave || false,
        isHandle: isHandle || false,
    };
}

/**
 * A patch may carry a `related` sub-schema for a field the target describes
 * without one -- the same field named twice in an arch where only one node has
 * a sub-view, or a widget dependency that declared an x2many with a scalar
 * type. Both readers below then dereferenced `activeField.related.activeFields`
 * on `undefined` and killed the whole asset bundle with a `TypeError` that
 * named neither the field nor the view. Adopting the patch's sub-schema is what
 * the caller means in every such case: the two nodes describe one field, and
 * the richer description wins.
 *
 * @param {Record<string, any>} activeField
 * @returns {{ activeFields: Record<string, any>, fields: Record<string, any> }}
 */
function ensureRelated(activeField) {
    if (!activeField.related) {
        activeField.related = { activeFields: {}, fields: {} };
    }
    return activeField.related;
}

/**
 * @param {Record<string, any>} activeFields
 * @returns {Record<string, any>}
 */
export function cloneActiveFields(activeFields) {
    /** @type {Record<string, any>} */
    const cloned = {};
    for (const [fieldName, activeField] of Object.entries(activeFields)) {
        const copy = { ...activeField };
        if (copy.related) {
            copy.related = {
                ...copy.related,
                activeFields: cloneActiveFields(copy.related.activeFields || {}),
                fields: { ...(copy.related.fields || {}) },
            };
        }
        cloned[fieldName] = copy;
    }
    return cloned;
}

/**
 * @param {Record<string, any>} activeFields
 * @param {Record<string, any>} fields
 * @param {any[]} [fieldDependencies]
 * @returns {void}
 */
export function addFieldDependencies(activeFields, fields, fieldDependencies = []) {
    if (fieldDependencies.length) {
        invalidateModifierDependencies(activeFields);
        invalidateAggregateSpecs(fields);
    }
    for (const field of fieldDependencies) {
        if (field.optional && !fields[field.name]) {
            continue;
        }
        const alreadyActive = field.name in activeFields;
        if (!("readonly" in field)) {
            field.readonly = !field.written;
        }
        if (alreadyActive) {
            if (!field.written) {
                patchActiveFields(activeFields[field.name], makeActiveField(field));
            }
        } else {
            activeFields[field.name] = makeActiveField(field);
            if (isX2Many(field)) {
                activeFields[field.name].related = {
                    activeFields: {},
                    fields: {},
                };
            }
        }
        if (!fields[field.name]) {
            const newField = omit(
                field,
                "context",
                "invisible",
                "required",
                "readonly",
                "onChange",
            );
            fields[field.name] = newField;
            if (newField.type === "selection" && !Array.isArray(newField.selection)) {
                newField.selection = [];
            }
        }
    }
}

/**
 * @param {Record<string, any>} activeField
 * @param {Record<string, any>} extra
 * @returns {void}
 */
function completeActiveField(activeField, extra) {
    if (extra.related) {
        const related = ensureRelated(activeField);
        invalidateModifierDependencies(related.activeFields);
        invalidateAggregateSpecs(related.fields);
        for (const fieldName of Object.keys(extra.related.activeFields)) {
            if (fieldName in related.activeFields) {
                completeActiveField(
                    related.activeFields[fieldName],
                    extra.related.activeFields[fieldName],
                );
            } else {
                related.activeFields[fieldName] = {
                    ...extra.related.activeFields[fieldName],
                };
            }
        }
        Object.assign(related.fields, extra.related.fields);
    }
}

/**
 * @param {Record<string, any>} activeFields
 * @param {Record<string, any>} extraActiveFields
 * @returns {void}
 */
export function completeActiveFields(activeFields, extraActiveFields) {
    invalidateModifierDependencies(activeFields);
    for (const fieldName of Object.keys(extraActiveFields)) {
        const extraActiveField = {
            ...extraActiveFields[fieldName],
            invisible: "True",
        };
        if (fieldName in activeFields) {
            completeActiveField(activeFields[fieldName], extraActiveField);
        } else {
            activeFields[fieldName] = extraActiveField;
        }
    }
}

/**
 * @param {Record<string, any>} property
 * @returns {Record<string, any>}
 */
export function createPropertyActiveField(property) {
    const { type } = property;

    const activeField = makeActiveField();
    if (isX2ManyType(type)) {
        activeField.related = {
            fields: {
                id: { name: "id", type: "integer" },
                display_name: { name: "display_name", type: "char" },
            },
            activeFields: {
                id: makeActiveField({ readonly: true }),
                display_name: makeActiveField(),
            },
        };
    }
    return activeField;
}

/**
 * `null` is accepted because the dominant caller is `Element.getAttribute`,
 * which answers `string | null` for an absent attribute -- and an absent
 * modifier is exactly what `undefined` already means here.
 *
 * @param {boolean | string | null | undefined} mod1
 * @param {boolean | string | null | undefined} mod2
 * @param {"AND" | "OR"} operator
 * @returns {boolean | string | null | undefined}
 */
export function combineModifiers(mod1, mod2, operator) {
    if (operator !== "AND" && operator !== "OR") {
        throw new Error(
            `Operator provided to "combineModifiers" must be "AND" or "OR", received ${operator}`,
        );
    }
    if (
        mod1 === mod2 &&
        typeof mod1 === "string" &&
        mod1 !== "True" &&
        mod1 !== "False" &&
        mod1 !== ""
    ) {
        return mod1;
    }
    if (operator === "AND") {
        if (!mod1 || mod1 === "False" || !mod2 || mod2 === "False") {
            return "False";
        }
        if (mod1 === "True") {
            return mod2;
        }
        if (mod2 === "True") {
            return mod1;
        }
        return `(${mod1}) and (${mod2})`;
    } else if (operator === "OR") {
        if (mod1 === "True" || mod2 === "True") {
            return "True";
        }
        if (!mod1 || mod1 === "False") {
            return mod2;
        }
        if (!mod2 || mod2 === "False") {
            return mod1;
        }
        return `(${mod1}) or (${mod2})`;
    }
}

/**
 * @param {Record<string, any>} activeField
 * @param {Record<string, any>} patch
 * @returns {void}
 */
export function patchActiveFields(activeField, patch) {
    const before = [activeField.invisible, activeField.readonly, activeField.required];
    activeField.invisible = combineModifiers(
        activeField.invisible,
        patch.invisible,
        "AND",
    );
    activeField.readonly = combineModifiers(
        activeField.readonly,
        patch.readonly,
        "AND",
    );
    activeField.required = combineModifiers(activeField.required, patch.required, "OR");
    if (
        before[0] !== activeField.invisible ||
        before[1] !== activeField.readonly ||
        before[2] !== activeField.required
    ) {
        // The dependency graph is cached per activeFields map, and this
        // function is handed one field without its owner. Bump the epoch so
        // every cached graph is recomputed on next read rather than relying on
        // each caller to remember which map it just changed.
        invalidateAllModifierDependencies();
    }
    activeField.onChange = activeField.onChange || patch.onChange;
    activeField.forceSave = activeField.forceSave || patch.forceSave;
    activeField.isHandle = activeField.isHandle || patch.isHandle;
    if (patch.related) {
        const related = ensureRelated(activeField);
        invalidateModifierDependencies(related.activeFields);
        invalidateAggregateSpecs(related.fields);
        for (const fieldName of Object.keys(patch.related.activeFields)) {
            if (fieldName in related.activeFields) {
                patchActiveFields(
                    related.activeFields[fieldName],
                    patch.related.activeFields[fieldName],
                );
            } else {
                related.activeFields[fieldName] = {
                    ...patch.related.activeFields[fieldName],
                };
            }
        }
        Object.assign(related.fields, patch.related.fields);
    }
    if ("limit" in patch) {
        activeField.limit = patch.limit;
    }
    if (patch.defaultOrderBy) {
        activeField.defaultOrderBy = patch.defaultOrderBy;
    }
}

/**
 * @param {any} declaration
 * @param {any} node
 * @returns {any[] | undefined}
 */
function resolveFieldDependencies(declaration, node) {
    return typeof declaration === "function" ? declaration(node) : declaration;
}

/**
 * @param {Record<string, any>} activeField
 * @param {any} fieldNode
 * @returns {void}
 */
function attachX2manyViews(activeField, fieldNode) {
    activeField.related = { activeFields: {}, fields: {} };
    const viewDescr = fieldNode.views?.[fieldNode.viewMode];
    if (!viewDescr) {
        return;
    }
    activeField.related = extractFieldsFromArchInfo(viewDescr, viewDescr.fields);
    activeField.limit = viewDescr.limit;
    activeField.defaultOrderBy = viewDescr.defaultOrder;

    if (fieldNode.views.form) {
        const formArchInfo = extractFieldsFromArchInfo(
            fieldNode.views.form,
            fieldNode.views.form.fields,
        );
        completeActiveFields(
            activeField.related.activeFields,
            formArchInfo.activeFields,
        );
        Object.assign(activeField.related.fields, formArchInfo.fields);
    }

    if (fieldNode.viewMode !== "default" && fieldNode.views.default) {
        const defaultArchInfo = extractFieldsFromArchInfo(
            fieldNode.views.default,
            fieldNode.views.default.fields,
        );
        for (const name of Object.keys(defaultArchInfo.activeFields)) {
            if (name in activeField.related.activeFields) {
                patchActiveFields(
                    activeField.related.activeFields[name],
                    defaultArchInfo.activeFields[name],
                );
            } else {
                activeField.related.activeFields[name] = {
                    ...defaultArchInfo.activeFields[name],
                };
            }
        }
        activeField.related.fields = Object.assign(
            {},
            defaultArchInfo.fields,
            activeField.related.fields,
        );
    }
}

/**
 * @param {any} fieldNode
 * @param {Record<string, any>} fields
 * @returns {Record<string, any>}
 */
function buildActiveFieldFromNode(fieldNode, fields) {
    const fieldName = fieldNode.name;
    const activeField = makeActiveField({
        context: fieldNode.context,
        invisible: combineModifiers(
            fieldNode.invisible,
            fieldNode.column_invisible,
            "OR",
        ),
        readonly: fieldNode.readonly,
        required: fieldNode.required,
        onChange: fieldNode.onChange,
        forceSave: fieldNode.forceSave,
        isHandle: fieldNode.isHandle,
    });
    if (isX2Many(fields[fieldName])) {
        attachX2manyViews(activeField, fieldNode);
        if (fieldNode.field?.useSubView) {
            activeField.required = "False";
        }
    }
    if (
        ["many2one", "many2one_reference"].includes(fields[fieldName].type) &&
        fieldNode.views
    ) {
        const viewDescr = fieldNode.views.default;
        activeField.related = extractFieldsFromArchInfo(viewDescr, viewDescr.fields);
    }
    return activeField;
}

/**
 * @param {Record<string, any>} activeFields
 * @param {Record<string, any>} fields
 * @param {any} fieldNode
 * @returns {void}
 */
function addNodeFieldDependencies(activeFields, fields, fieldNode) {
    if (fieldNode.field) {
        addFieldDependencies(
            activeFields,
            fields,
            resolveFieldDependencies(fieldNode.field.fieldDependencies, fieldNode),
        );
    }
    if (fieldNode.options?.placeholder_field) {
        addFieldDependencies(activeFields, fields, [
            {
                name: fieldNode.options.placeholder_field,
                type: fields[fieldNode.options.placeholder_field]?.type,
                readonly: true,
                optional: true,
            },
        ]);
    }
}

/**
 * @param {{ fieldNodes: Record<string, any>, widgetNodes?: Record<string, any> }} archInfo
 * @param {Record<string, any>} fields
 * @returns {{ activeFields: Record<string, any>, fields: Record<string, any> }}
 */
export function extractFieldsFromArchInfo({ fieldNodes, widgetNodes }, fields) {
    /** @type {Record<string, any>} */
    const activeFields = {};
    for (const fieldNode of Object.values(fieldNodes)) {
        const fieldName = fieldNode.name;
        const activeField = buildActiveFieldFromNode(fieldNode, fields);
        if (fieldName in activeFields) {
            patchActiveFields(activeFields[fieldName], activeField);
        } else {
            activeFields[fieldName] = activeField;
        }
        addNodeFieldDependencies(activeFields, fields, fieldNode);
    }

    for (const widgetInfo of Object.values(widgetNodes || {})) {
        addFieldDependencies(
            activeFields,
            fields,
            resolveFieldDependencies(widgetInfo.widget.fieldDependencies, widgetInfo),
        );
    }
    return { activeFields, fields };
}
