// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/field_metadata */

/**
 * @param {boolean | string} value
 * @returns {string}
 */

import { omit } from "@web/core/utils/collections/objects";

import { invalidateAggregateSpecs } from "./field_values.js";
import { invalidateModifierDependencies } from "./record_utils.js";

function convertBoolToPyExpr(value) {
    if (value === true || value === false) {
        return value ? "True" : "False";
    }
    return value;
}

/**
 * @typedef {{
 *   context?: string;
 *   invisible?: boolean | string;
 *   readonly?: boolean | string;
 *   required?: boolean | string;
 *   onChange?: boolean | string;
 *   forceSave?: boolean;
 *   isHandle?: boolean;
 * }} ActiveFieldOptions
 */

/**
 * Registry validation for a `fieldDependencies` declaration, shared by the
 * `fields` and `view_widgets` registries so the two cannot drift.
 *
 * Only `name` is required: {@link addFieldDependencies} reads `optional` and
 * `readonly`, uses `type` solely to bootstrap an x2many `related` bucket, and
 * forwards the rest to {@link makeActiveField}. Modifiers are python
 * expressions as often as booleans, hence `[Boolean, String]`.
 *
 * The element schema must nest under `element`; a `shape` sibling of `element`
 * is silently ignored by owl's validator (it checks `element` first).
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

/**
 * @param {ActiveFieldOptions} [options]
 * @returns {Object}
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

export function addFieldDependencies(activeFields, fields, fieldDependencies = []) {
    if (fieldDependencies.length) {
        invalidateModifierDependencies(activeFields);
        invalidateAggregateSpecs(fields);
    }
    for (const field of fieldDependencies) {
        if (field.optional && !fields[field.name]) {
            continue;
        }
        // A dependency is a *read* by default, and that default is load-bearing:
        // a readonly active field is dropped from web_save, so leaving it
        // implicit on a field the widget writes makes the write vanish -- the
        // value round-trips through the input and is silently lost.
        //
        // `readonly: false` is not the cure, because it is not "don't care":
        // patchActiveFields combines readonly with AND, so a false dependency
        // *overrides* an arch `readonly="..."` on the same field and unlocks it.
        //
        // `written: true` is the third case -- "this widget edits the field".
        // It must be writable when this declaration is what puts it in the view,
        // and when the arch already carries the field the arch keeps ownership
        // of its modifiers, so no patch is applied at all.
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
            if (["one2many", "many2many"].includes(field.type)) {
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

function completeActiveField(activeField, extra) {
    if (extra.related) {
        invalidateModifierDependencies(activeField.related.activeFields);
        invalidateAggregateSpecs(activeField.related.fields);
        for (const fieldName of Object.keys(extra.related.activeFields)) {
            if (fieldName in activeField.related.activeFields) {
                completeActiveField(
                    activeField.related.activeFields[fieldName],
                    extra.related.activeFields[fieldName],
                );
            } else {
                activeField.related.activeFields[fieldName] = {
                    ...extra.related.activeFields[fieldName],
                };
            }
        }
        Object.assign(activeField.related.fields, extra.related.fields);
    }
}

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

export function createPropertyActiveField(property) {
    const { type } = property;

    const activeField = makeActiveField();
    if (type === "one2many" || type === "many2many") {
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

export function patchActiveFields(activeField, patch) {
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
    activeField.onChange = activeField.onChange || patch.onChange;
    activeField.forceSave = activeField.forceSave || patch.forceSave;
    activeField.isHandle = activeField.isHandle || patch.isHandle;
    if (patch.related) {
        const related = activeField.related;
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

export function extractFieldsFromArchInfo({ fieldNodes, widgetNodes }, fields) {
    const activeFields = {};
    for (const fieldNode of Object.values(fieldNodes)) {
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
        if (["one2many", "many2many"].includes(fields[fieldName].type)) {
            activeField.related = {
                activeFields: {},
                fields: {},
            };
            if (fieldNode.views) {
                const viewDescr = fieldNode.views[fieldNode.viewMode];
                if (viewDescr) {
                    activeField.related = extractFieldsFromArchInfo(
                        viewDescr,
                        viewDescr.fields,
                    );
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
                        for (const fieldName of Object.keys(
                            defaultArchInfo.activeFields,
                        )) {
                            if (fieldName in activeField.related.activeFields) {
                                patchActiveFields(
                                    activeField.related.activeFields[fieldName],
                                    defaultArchInfo.activeFields[fieldName],
                                );
                            } else {
                                activeField.related.activeFields[fieldName] = {
                                    ...defaultArchInfo.activeFields[fieldName],
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
            }
            if (fieldNode.field?.useSubView) {
                activeField.required = "False";
            }
        }
        if (
            ["many2one", "many2one_reference"].includes(fields[fieldName].type) &&
            fieldNode.views
        ) {
            const viewDescr = fieldNode.views.default;
            activeField.related = extractFieldsFromArchInfo(
                viewDescr,
                viewDescr.fields,
            );
        }

        if (fieldName in activeFields) {
            patchActiveFields(activeFields[fieldName], activeField);
        } else {
            activeFields[fieldName] = activeField;
        }

        if (fieldNode.field) {
            let fieldDependencies = fieldNode.field.fieldDependencies;
            if (typeof fieldDependencies === "function") {
                fieldDependencies = fieldDependencies(fieldNode);
            }
            addFieldDependencies(activeFields, fields, fieldDependencies);
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

    for (const widgetInfo of Object.values(widgetNodes || {})) {
        let fieldDependencies = widgetInfo.widget.fieldDependencies;
        if (typeof fieldDependencies === "function") {
            fieldDependencies = fieldDependencies(widgetInfo);
        }
        addFieldDependencies(activeFields, fields, fieldDependencies);
    }
    return { activeFields, fields };
}
