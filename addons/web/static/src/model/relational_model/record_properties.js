// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_properties - Dynamic property-field expansion: splice per-property definitions into the record schema and shape per-property values */

/**
 * Properties-field expansion logic.
 *
 * When a record carries a "properties" field, the server returns an array
 * of property definitions where each entry describes a sub-field
 * (name, type, value, optional comodel/selection/tags, etc.). This
 * helper walks that array and:
 *
 *   1. **Splices the per-property field into ``record.fields``** under the
 *      composite name ``${parentFieldName}.${property.name}``, with the
 *      ``relatedPropertyField`` back-pointer and the right ``sortable``
 *      flag (false for relational/tag types so the UI hides the sort
 *      affordance for those columns).
 *   2. **Registers the activeField** via
 *      {@link field_metadata.createPropertyActiveField}, then patches in
 *      the ``relatedPropertyField`` with the parent m2o's id and
 *      display_name so the view can render the breadcrumb back to the
 *      definition record.
 *   3. **Shapes the per-property value** by type — m2m builds a
 *      StaticList datapoint via ``record._createStaticListDatapoint``,
 *      m2o handles the "No Access" placeholder (server returns ``null``
 *      for ``display_name`` when the user can read the id but not the
 *      target record), and scalars pass through unchanged.
 *
 * Returns a flat ``{ "<parentFieldName>.<propertyName>": value, ... }``
 * bag that the caller (``parseServerValues`` in record_value_transforms,
 * or ``preprocessPropertiesChanges`` in record_preprocessors) merges
 * into the parsed values object.
 *
 * Following the convention established in Phase 1–3, the helper receives
 * the ``RelationalRecord`` as its first argument and calls back into
 * instance-level methods (``record._createStaticListDatapoint``) and
 * state (``record.fields``, ``record.activeFields``) directly.
 *
 * **Why ``hasCurrentValues`` toggles the field overwrite.**  When the
 * helper is invoked from a *change*-driven path (``preprocessPropertiesChanges``,
 * which always passes a non-empty ``record.data``), the server may have
 * sent revised property definitions that need to replace the previously-
 * registered schema — so the field/activeField entries are rewritten
 * unconditionally. When invoked from an *initial-load* path (e.g.
 * ``parseServerValues``), the field/activeField are only created if
 * not already present, preserving any patches downstream code may have
 * applied to the definition since the last load.
 */

import { _t } from "@web/core/l10n/translation";

import { createPropertyActiveField } from "./field_metadata.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Extract all property values for a properties field, registering each
 * property as a synthetic field/activeField on the record.
 *
 * @param {RelationalRecord} record
 * @param {Object[]} properties array of property definitions sent by
 *  the server. Each entry must carry ``name`` and ``type``; relational
 *  types additionally carry ``comodel`` and ``value`` shaped per type.
 * @param {string} fieldName the parent properties-field name (the value
 *  the view's ``<field name="...">`` binds to)
 * @param {{ id?: number; display_name?: string } | false} parent the
 *  parsed m2o value at the ``definition_record`` field (the record that
 *  owns the property schema). May be ``false`` when the parent has not
 *  been set yet — the per-property ``relatedPropertyField`` will then
 *  carry ``id: undefined`` and ``displayName: undefined``.
 * @param {Object} [currentValues={}] existing parsed values; non-empty
 *  toggles the schema-rewrite path (see the module docstring's
 *  "Why ``hasCurrentValues`` toggles" note)
 * @returns {Object} flat bag keyed by ``${fieldName}.${property.name}``
 */
export function processProperties(
    record,
    properties,
    fieldName,
    parent,
    currentValues = {},
) {
    /** @type {Record<string, any>} */
    const data = {};

    const hasCurrentValues = Object.keys(currentValues).length > 0;
    for (const property of properties) {
        const propertyFieldName = `${fieldName}.${property.name}`;

        // Add Unknown Property Field and ActiveField
        if (hasCurrentValues || !record.fields[propertyFieldName]) {
            record.fields[propertyFieldName] = {
                ...property,
                name: propertyFieldName,
                relatedPropertyField: {
                    name: fieldName,
                },
                propertyName: property.name,
                relation: property.comodel,
                sortable: !["many2one", "many2many", "tags"].includes(property.type),
            };
        }
        if (hasCurrentValues || !record.activeFields[propertyFieldName]) {
            record.activeFields[propertyFieldName] =
                createPropertyActiveField(property);
        }

        if (!record.activeFields[propertyFieldName].relatedPropertyField) {
            record.activeFields[propertyFieldName].relatedPropertyField = {
                name: fieldName,
                id: parent?.id,
                displayName: parent?.display_name,
            };
        }

        // Extract property data
        if (property.type === "many2many") {
            let staticList = currentValues[propertyFieldName];
            if (!staticList) {
                staticList = record._createStaticListDatapoint(
                    (property.value || []).map((rec) => ({
                        id: rec[0],
                        display_name: rec[1],
                    })),
                    propertyFieldName,
                );
            }
            data[propertyFieldName] = staticList;
        } else if (property.type === "many2one") {
            data[propertyFieldName] =
                property.value && property.value.display_name === null
                    ? {
                          id: property.value.id,
                          display_name: _t("No Access"),
                      }
                    : property.value;
        } else {
            data[propertyFieldName] = property.value ?? false;
        }
    }

    return data;
}
