// @ts-check
/** @odoo-module native */

import { evalPartialContext } from "@web/core/context";
import { orderByToString } from "@web/core/utils/order_by";

/**
 * @param {Record<string, any>} activeFields
 * @param {Record<string, any>} fields
 * @param {string} fieldName
 * @param {Record<string, any>} evalContext
 * @returns {Record<string, any> | undefined}
 */
function getFieldContextForSpec(activeFields, fields, fieldName, evalContext) {
    let context = activeFields[fieldName].context;
    if (!context || context === "{}") {
        context = fields[fieldName].context || {};
    } else {
        context = evalPartialContext(context, evalContext);
    }
    if (Object.keys(context).length > 0) {
        return context;
    }
}

/**
 * @param {Record<string, any>} fieldSpec
 * @param {Record<string, any> | undefined} context
 */
function setSpecContext(fieldSpec, context) {
    if (context) {
        fieldSpec.context = context;
    }
}

/**
 * @typedef {object} SpecScope
 * @property {Record<string, any>} activeFields
 * @property {Record<string, any>} fields
 * @property {Record<string, any>} evalContext
 * @property {Record<string, any>} [orderBys]
 * @property {boolean} [withInvisible]
 */

/**
 * @param {Record<string, any>} fieldSpec
 * @param {string} fieldName
 * @param {SpecScope} scope
 * @param {Record<string, any>} related
 * @returns {void}
 */
function specifyRelatedFields(fieldSpec, fieldName, scope, related) {
    const { activeFields, fields, evalContext } = scope;
    fieldSpec.fields = getFieldsSpec(related.activeFields, related.fields, evalContext);
    setSpecContext(
        fieldSpec,
        getFieldContextForSpec(activeFields, fields, fieldName, evalContext),
    );
}

/**
 * @param {Record<string, any>} fieldSpec
 * @param {string} fieldName
 * @param {SpecScope} scope
 * @param {{ related: any, limit: any, defaultOrderBy: any, isAlwaysInvisible: boolean }} info
 * @returns {void}
 */
function specifyX2many(fieldSpec, fieldName, scope, info) {
    const { activeFields, fields, evalContext, orderBys, withInvisible } = scope;
    const { related, limit, defaultOrderBy, isAlwaysInvisible } = info;
    if (!related || (!withInvisible && isAlwaysInvisible)) {
        return;
    }
    fieldSpec.fields = getFieldsSpec(
        related.activeFields,
        related.fields,
        evalContext,
        {
            withInvisible,
        },
    );
    setSpecContext(
        fieldSpec,
        getFieldContextForSpec(activeFields, fields, fieldName, evalContext),
    );
    fieldSpec.limit = limit;
    const orderBy = orderBys?.[fieldName] || defaultOrderBy || [];
    if (orderBy.length) {
        fieldSpec.order = orderByToString(orderBy);
    }
}

/**
 * @param {Record<string, any>} fieldSpec
 * @param {string} fieldName
 * @param {SpecScope} scope
 * @param {{ related: any, isAlwaysInvisible: boolean }} info
 * @returns {void}
 */
function specifyMany2one(fieldSpec, fieldName, scope, info) {
    fieldSpec.fields = {};
    if (info.isAlwaysInvisible) {
        return;
    }
    if (info.related) {
        specifyRelatedFields(fieldSpec, fieldName, scope, info.related);
    } else {
        const { activeFields, fields, evalContext } = scope;
        setSpecContext(
            fieldSpec,
            getFieldContextForSpec(activeFields, fields, fieldName, evalContext),
        );
    }
    fieldSpec.fields.display_name = {};
}

/**
 * @param {Record<string, any>} fieldsSpec
 * @param {string[]} propertyFieldNames
 * @param {Record<string, any>} fields
 * @returns {void}
 */
function specifyPropertyDefinitionNames(fieldsSpec, propertyFieldNames, fields) {
    for (const fieldName of propertyFieldNames) {
        const fieldSpec = fieldsSpec[fields[fieldName].definition_record];
        if (!fieldSpec) {
            continue;
        }
        fieldSpec.fields = fieldSpec.fields || {};
        fieldSpec.fields.display_name = {};
    }
}

/**
 * @param {Record<string, any>} activeFields
 * @param {Record<string, any>} fields
 * @param {Record<string, any>} evalContext
 * @param {{ orderBys?: Record<string, any>, withInvisible?: boolean }} [options]
 * @returns {Record<string, any>}
 */
export function getFieldsSpec(
    activeFields,
    fields,
    evalContext,
    { orderBys, withInvisible } = {},
) {
    /** @type {Record<string, any>} */
    const fieldsSpec = {};
    /** @type {string[]} */
    const propertyFieldNames = [];
    /** @type {SpecScope} */
    const scope = { activeFields, fields, evalContext, orderBys, withInvisible };

    for (const fieldName of Object.keys(activeFields)) {
        if (fields[fieldName].relatedPropertyField) {
            continue;
        }
        const { related, limit, defaultOrderBy, invisible } = activeFields[fieldName];
        const isAlwaysInvisible = invisible === "True" || invisible === "1";
        const fieldSpec = {};
        fieldsSpec[fieldName] = fieldSpec;
        switch (fields[fieldName].type) {
            case "one2many":
            case "many2many":
                specifyX2many(fieldSpec, fieldName, scope, {
                    related,
                    limit,
                    defaultOrderBy,
                    isAlwaysInvisible,
                });
                break;
            case "many2one":
            case "reference":
                specifyMany2one(fieldSpec, fieldName, scope, {
                    related,
                    isAlwaysInvisible,
                });
                break;
            case "many2one_reference":
                if (related && !isAlwaysInvisible) {
                    specifyRelatedFields(fieldSpec, fieldName, scope, related);
                }
                break;
            case "properties":
                propertyFieldNames.push(fieldName);
                break;
        }
    }

    specifyPropertyDefinitionNames(fieldsSpec, propertyFieldNames, fields);
    return fieldsSpec;
}
