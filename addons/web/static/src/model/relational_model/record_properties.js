// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_properties - Dynamic property-field expansion: splice per-property definitions into the record schema and shape per-property values */

/**
 * Properties-field expansion logic.
 *
 * The server returns an array of property definitions for a "properties"
 * field (name, type, value, optional comodel/selection/tags, etc.). This
 * helper walks it and, for each property:
 *
 *   1. Splices the field into ``record.fields`` under
 *      ``${parentFieldName}.${property.name}``, with the
 *      ``relatedPropertyField`` back-pointer and ``sortable: false`` for
 *      relational/tag types (the UI hides sorting for those columns).
 *   2. Registers the activeField via
 *      {@link field_metadata.createPropertyActiveField}, patching in the
 *      parent m2o's id/display_name so the view can render the breadcrumb
 *      back to the definition record.
 *   3. Shapes the value by type: m2m builds a StaticList datapoint, m2o
 *      handles the "No Access" placeholder (server sends ``null``
 *      ``display_name`` when the id is readable but the record isn't),
 *      scalars pass through unchanged.
 *
 * Returns a flat ``{ "<parentFieldName>.<propertyName>": value, ... }``
 * bag merged into the parsed values by the caller (``parseServerValues``
 * or ``preprocessPropertiesChanges``).
 *
 * ``hasCurrentValues`` gates whether the field/activeField entries are
 * rewritten: on a *change*-driven call (non-empty ``record.data``) the
 * server may have sent revised definitions that must replace the
 * registered schema, so they're always rewritten; on *initial-load* they're
 * only created if absent, preserving any patches applied since last load.
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
