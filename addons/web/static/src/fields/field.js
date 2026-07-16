// @ts-check
/** @odoo-module native */

/** @module @web/fields/field - Generic Field component that resolves and renders the appropriate field widget from the registry */

import { Component, onWillRender, xml } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { evaluateBooleanExpr, evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { getClassNameFromDecoration } from "@web/core/utils/decorations";
import { getFieldContext } from "@web/model/relational_model/utils";

import { getTooltipInfo } from "./field_tooltip.js";

const fieldRegistry = registry.category("fields");

const validFieldTypes = [
    "binary",
    "boolean",
    "json",
    "integer",
    "float",
    "monetary",
    "properties",
    "properties_definition",
    "reference",
    "many2one_reference",
    "many2one",
    "one2many",
    "many2many",
    "selection",
    "date",
    "datetime",
    "char",
    "text",
    "html",
];

/**
 * Shape of a single ``supportedAttributes`` / ``supportedOptions`` entry.
 *
 * Deliberately permissive: registry validation QUARANTINES failing entries
 * in production (see @web/core/registry ``validateSchema``), so an
 * over-strict shape would silently remove field widgets fleet-wide. The
 * shape below was derived from a sweep of every declaration in community,
 * enterprise and agromarin (172 entries, 2026-07):
 *
 * - ``name`` is the only universal key (e.g. enterprise's
 *   ``integration_state_selection`` declares no ``label``) — everything
 *   else is optional.
 * - ``default`` mirrors the option's runtime type: booleans (floatField),
 *   numbers (integerField), strings and objects (hr_skills
 *   ``formatted_date``) all occur — any type is accepted.
 * - ``choices[].value`` is not always a string (dateTimeField uses
 *   booleans) — any type is accepted.
 * - ``"*": true`` tolerates addon-specific extras (e.g. ``placeholder``
 *   on dateTimeField's options) without quarantining the widget.
 */
const supportedInfoEntryShape = {
    name: String,
    label: { type: String, optional: true },
    type: { type: String, optional: true },
    availableTypes: { type: Array, element: String, optional: true },
    default: { optional: true },
    help: { type: String, optional: true },
    choices: /* choices if type == selection */ {
        type: Array,
        element: {
            type: Object,
            shape: {
                label: { type: String, optional: true },
                value: { optional: true },
                "*": true,
            },
        },
        optional: true,
    },
    /** If true, listed fields come from the relation (e.g. many2many_tags: 'field' searches on the relation). */
    isRelationalField: { type: Boolean, optional: true },
    placeholder: { type: String, optional: true },
    "*": true,
};

const supportedInfoValidation = {
    type: Array,
    optional: true,
    element: [
        { type: Object, shape: supportedInfoEntryShape },
        // stock_action_field composes supportedOptions via a nested
        // Object.values(...) (not spread) — tolerate one level of nesting.
        {
            type: Array,
            element: { type: Object, shape: supportedInfoEntryShape },
        },
    ],
};

fieldRegistry.addValidation({
    component: { validate: (c) => c.prototype instanceof Component },
    displayName: { type: String, optional: true },
    supportedAttributes: supportedInfoValidation,
    supportedOptions: supportedInfoValidation,
    supportedTypes: {
        type: Array,
        element: String,
        optional: true,
        validate: (array) => array.every((x) => validFieldTypes.includes(x)),
    },
    extractProps: { type: Function, optional: true },
    isEmpty: { type: Function, optional: true },
    isValid: { type: Function, optional: true }, // Override the validation for the validation visual feedbacks
    additionalClasses: { type: Array, element: String, optional: true },
    fieldDependencies: {
        type: [
            Function,
            {
                type: Array,
                element: Object,
                shape: { name: String, type: String },
            },
        ],
        optional: true,
    },
    relatedFields: {
        // Function forms (e.g. many2ManyTagsField) are opaque to the schema —
        // only array literals are shape-checked. ``"*": true`` tolerates extra
        // description keys; ``name`` is the only universal one.
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
    },
    useSubView: { type: Boolean, optional: true },
    label: { type: [String, { value: false }], optional: true },
    listViewWidth: {
        type: [
            Number,
            {
                type: Array,
                element: Number,
                validate: (array) => array.length === 1 || array.length === 2,
            },
            Function,
        ],
        optional: true,
    },
});

class DefaultField extends Component {
    static template = xml``;
    static props = ["*"];
}

// Warn once per widget/type miss, not once per component instance.
const warnedWidgetMisses = new Set();

/**
 * Resolves a field descriptor from the field registry, searching with optional
 * jsClass and viewType prefixes (e.g. "list.char", "char").
 *
 * @param {string} fieldType - ORM field type (e.g. "char", "many2one", "float")
 * @param {string} [widget] - Widget override from the XML `widget` attribute
 * @param {string} [viewType] - View type prefix for scoped lookups (e.g. "list", "form")
 * @param {string} [jsClass] - JS class prefix for compound lookups (e.g. "sale_order")
 * @returns {{ component: import("@odoo/owl").ComponentConstructor, extractProps?: Function, supportedTypes?: string[], isEmpty?: Function, isValid?: Function, additionalClasses?: string[], relatedFields?: Array | Function, useSubView?: boolean, [key: string]: any }}
 */
export function getFieldFromRegistry(fieldType, widget, viewType, jsClass) {
    const prefixes = jsClass ? [jsClass, viewType, ""] : [viewType, ""];
    /** @param {string} key */
    const findInRegistry = (key) => {
        for (const prefix of prefixes) {
            const _key = prefix ? `${prefix}.${key}` : key;
            if (fieldRegistry.contains(_key)) {
                return fieldRegistry.get(_key);
            }
        }
    };
    if (widget) {
        const field = findInRegistry(widget);
        const warningKey = `${widget}|${fieldType}`;
        if (field) {
            if (
                field.supportedTypes &&
                !field.supportedTypes.includes(fieldType) &&
                !warnedWidgetMisses.has(warningKey)
            ) {
                warnedWidgetMisses.add(warningKey);
                console.warn(
                    `The widget: ${widget} don't support the type ${fieldType}`,
                );
            }
            return field;
        }
        if (!warnedWidgetMisses.has(warningKey)) {
            warnedWidgetMisses.add(warningKey);
            console.warn(`Missing widget: ${widget} for field of type ${fieldType}`);
        }
    }
    return /** @type {any} */ (
        findInRegistry(fieldType) || { component: DefaultField }
    );
}

/**
 * Computes visual feedback state for a field widget (readonly, required, invalid, empty).
 *
 * @param {{ isEmpty?: (record: any, fieldName: string) => boolean, isValid?: (record: any, fieldName: string, fieldInfo: any) => boolean }} field - Resolved field descriptor
 * @param {import("@web/model/relational_model/record").RelationalRecord} record
 * @param {string} fieldName
 * @param {{ readonly?: string, required?: string }} fieldInfo - Parsed field node info
 * @returns {{ readonly: boolean, required: boolean, invalid: boolean, empty: boolean }}
 */
export function fieldVisualFeedback(field, record, fieldName, fieldInfo) {
    const readonly = evaluateBooleanExpr(
        fieldInfo.readonly,
        record.evalContextWithVirtualIds,
    );
    const required = evaluateBooleanExpr(
        fieldInfo.required,
        record.evalContextWithVirtualIds,
    );
    const inEdit = record.isInEdition;

    let empty = !record.isNew;
    if ("isEmpty" in field) {
        const isEmpty = /** @type {(record: any, fieldName: string) => boolean} */ (
            field.isEmpty
        );
        empty = empty && isEmpty(record, fieldName);
    } else {
        empty = empty && !record.data[fieldName];
    }
    empty = inEdit ? empty && readonly : empty;
    return {
        readonly,
        required,
        invalid: field.isValid
            ? !field.isValid(record, fieldName, fieldInfo)
            : record.isFieldInvalid(fieldName),
        empty,
    };
}

/**
 * Builds a normalized fieldInfo object for a property field (dynamic fields
 * defined via the Properties system, not XML arch).
 *
 * @param {{ name: string, type: string, widget?: string, string?: string, relation?: string, domain?: string, selection?: Array, tags?: Array, relatedPropertyField?: any }} propertyField
 * @returns {{ name: string, type: string, widget: string, string?: string, field: ReturnType<typeof getFieldFromRegistry>, options: Object, readonly: string, required: string, invisible: string, column_invisible: string, context: string, attrs: Object, decorations: Object, [key: string]: any }}
 */
export function getPropertyFieldInfo(propertyField) {
    const { name, relatedPropertyField, string, type, widget } = propertyField;

    // ``field`` is assigned below via ``getFieldFromRegistry``; without the
    // widen, TS infers a literal type here and complains at the return.
    /** @type {any} */
    const fieldInfo = {
        name,
        string,
        type,
        widget: widget || type,
        options: {},
        column_invisible: "False",
        invisible: "False",
        readonly: "False",
        required: "False",
        attrs: {},
        relatedPropertyField,

        context: "{}",
        help: undefined,
        onChange: false,
        forceSave: false,
        decorations: {},
    };

    if (type === "many2one" || type === "many2many") {
        const { domain, relation } = propertyField;
        fieldInfo.relation = relation;
        fieldInfo.domain = domain;

        if (relation === "res.users" || relation === "res.partner") {
            fieldInfo.widget =
                propertyField.type === "many2one"
                    ? "many2one_avatar"
                    : "many2many_tags_avatar";
        } else {
            fieldInfo.widget =
                propertyField.type === "many2one" ? type : "many2many_tags";
        }
    } else if (type === "tags") {
        fieldInfo.tags = propertyField.tags;
        fieldInfo.widget = `property_tags`;
    } else if (type === "selection") {
        fieldInfo.selection = propertyField.selection;
    }

    fieldInfo.field = getFieldFromRegistry(propertyField.type, fieldInfo.widget);
    let { relatedFields } = fieldInfo.field;
    if (relatedFields) {
        if (relatedFields instanceof Function) {
            relatedFields = relatedFields({ options: {}, attrs: {} });
        }
        fieldInfo.relatedFields = Object.fromEntries(
            relatedFields.map((f) => [f.name, f]),
        );
    }

    return fieldInfo;
}
/**
 * Generic Field component that resolves the appropriate widget from the
 * field registry and renders it.
 *
 * Arch parsing (the static ``parseFieldNode`` that used to live here as
 * a class member) moved to ``@web/views/field_arch`` because the
 * XML→fieldInfo translation is a view-layer concern, not a component
 * concern. Callers that previously did ``Field.parseFieldNode(...)``
 * now do ``import { parseFieldNode } from "@web/views/field_arch"``.
 */
export class Field extends Component {
    static template = "web.Field";
    static props = ["fieldInfo?", "*"];

    setup() {
        if (this.props.fieldInfo) {
            this.field = this.props.fieldInfo.field;
        } else {
            const fieldType = this.props.record.fields[this.props.name].type;
            this.field = getFieldFromRegistry(fieldType, this.props.type);
        }
        // The template reads `tooltip` twice: build (and stringify) the
        // tooltip info at most once per render.
        onWillRender(() => {
            this._tooltip = this.computeTooltip();
        });
    }

    /** @returns {Record<string, boolean>} OWL dynamic class map for the field wrapper element */
    get classNames() {
        const { class: _class, fieldInfo, name, record } = this.props;
        const { readonly, required, invalid, empty } = fieldVisualFeedback(
            this.field,
            record,
            name,
            fieldInfo || {},
        );
        const classNames = {
            o_field_widget: true,
            o_readonly_modifier: readonly,
            o_required_modifier: required,
            o_field_invalid: invalid,
            o_field_empty: empty,
            [`o_field_${this.type}`]: true,
            ...(_class ? { [_class]: true } : {}),
        };
        if (this.field.additionalClasses) {
            for (const cls of this.field.additionalClasses) {
                classNames[cls] = true;
            }
        }

        // Decoration classNames from arch attrs (e.g. decoration-danger="other_field = 5");
        // only text-decoration is handled here.
        if (fieldInfo?.decorations) {
            const { decorations } = fieldInfo;
            for (const decoName of Object.keys(decorations)) {
                const value = evaluateBooleanExpr(
                    decorations[decoName],
                    record.evalContextWithVirtualIds,
                );
                classNames[getClassNameFromDecoration(decoName)] = value;
            }
        }

        return classNames;
    }

    /** @returns {string} ORM field type or explicit `type` prop override */
    get type() {
        return this.props.type || this.props.record.fields[this.props.name].type;
    }

    /** @returns {Object} Props forwarded to the resolved field widget component, merged from extractProps and own props */
    get fieldComponentProps() {
        const record = this.props.record;
        let readonly = this.props.readonly || false;

        let propsFromNode = {};
        if (this.props.fieldInfo) {
            let fieldInfo = this.props.fieldInfo;
            readonly =
                readonly ||
                evaluateBooleanExpr(
                    fieldInfo.readonly,
                    record.evalContextWithVirtualIds,
                );

            if (this.field.extractProps) {
                if (this.props.attrs) {
                    fieldInfo = {
                        ...fieldInfo,
                        attrs: { ...fieldInfo.attrs, ...this.props.attrs },
                    };
                }
                if (
                    fieldInfo.attrs.placeholder ||
                    fieldInfo.options.placeholder_field
                ) {
                    // ``fieldInfo`` is the parsed arch node, shared across every
                    // Field instance for this node (e.g. all rows of a list column).
                    // The placeholder is record-specific, so mutating it in place
                    // would pollute the shared node (and could trigger render loops
                    // if the arch node became reactive) — shallow-copy instead, only
                    // when a placeholder is actually in play.
                    fieldInfo = {
                        ...fieldInfo,
                        placeholder:
                            record.data[fieldInfo.options.placeholder_field] ||
                            fieldInfo.attrs.placeholder,
                    };
                }

                const dynamicInfo = {
                    get context() {
                        return getFieldContext(
                            record,
                            fieldInfo.name,
                            fieldInfo.context,
                        );
                    },
                    domain() {
                        const evalContext = record.evalContext;
                        if (fieldInfo.domain) {
                            return new Domain(
                                evaluateExpr(fieldInfo.domain, evalContext),
                            ).toList();
                        }
                    },
                    required: evaluateBooleanExpr(
                        fieldInfo.required,
                        record.evalContextWithVirtualIds,
                    ),
                    readonly: readonly,
                };
                propsFromNode = this.field.extractProps(fieldInfo, dynamicInfo);
            }
        }

        const props = { ...this.props };
        delete props.style;
        delete props.class;
        delete props.showTooltip;
        delete props.fieldInfo;
        delete props.attrs;
        delete props.type;
        delete props.readonly;

        return {
            readonly: readonly || !record.isInEdition || false,
            ...propsFromNode,
            ...props,
        };
    }

    /** @returns {string | false} JSON-serialized tooltip data, or false if tooltip is disabled */
    computeTooltip() {
        if (!this.props.showTooltip) {
            return false;
        }
        const field = this.props.record.fields[this.props.name];
        const fieldInfo = this.props.fieldInfo || {};
        // Cheap precheck: only build (and stringify) the tooltip info when
        // it will actually be displayed.
        if (!odoo.debug && !(fieldInfo.help ?? field.help)) {
            return false;
        }
        return getTooltipInfo({ field, fieldInfo });
    }

    /** @returns {string | false} JSON-serialized tooltip data, or false if tooltip is disabled */
    get tooltip() {
        // _tooltip is always set before render (onWillRender above), which is
        // the only time the template reads this getter.
        return /** @type {string | false} */ (this._tooltip);
    }
}
