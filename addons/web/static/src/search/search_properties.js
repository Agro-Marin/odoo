// @ts-check
/** @odoo-module native */

/** @module @web/search/search_properties - Property-field search logic for lazy-loading definitions and creating search items */

/**
 * All functions take the SearchModel instance as first argument (delegation
 * pattern) to preserve subclass polymorphism.
 */

/** SearchModel widened so this delegate module can read instance state
 * set across SearchModel's many methods. */
/** @typedef {any} SearchModel */

/**
 * Generate (or refresh) property-based search items for a "properties" field.
 *
 * @param {SearchModel} searchModel - the SearchModel instance
 * @param {Object} searchItem - a search item of type "field" with fieldType "properties"
 * @returns {Promise<Object[]>} matching search items
 */

import { groupBy } from "@web/core/utils/collections/arrays";
export async function getSearchItemsProperties(searchModel, searchItem) {
    if (searchItem.type !== "field" || searchItem.fieldType !== "properties") {
        return [];
    }
    const field = searchModel.searchViewFields[searchItem.fieldName];
    const definitionRecord = field.definition_record;
    const result = await searchModel._fetchPropertiesDefinition(
        searchModel.resModel,
        searchItem.fieldName,
    );

    const searchItemIds = new Set();
    const existingFieldProperties = {};
    for (const item of Object.values(searchModel.searchItems)) {
        if (item.type === "field_property" && item.propertyItemId === searchItem.id) {
            existingFieldProperties[item.propertyFieldDefinition.name] = item;
        }
    }

    for (const { definitionRecordId, definitionRecordName, definitions } of result) {
        for (const definition of definitions) {
            if (definition.type === "separator") {
                continue;
            }
            const existingSearchItem = existingFieldProperties[definition.name];
            if (existingSearchItem) {
                // Already in the list (e.g. unfold properties, edit in a form, come
                // back): the label may have changed, so refresh the description.
                existingSearchItem.description = `${definition.string} (${definitionRecordName})`;
                searchItemIds.add(existingSearchItem.id);
                continue;
            }
            const id = searchModel.nextId++;
            const newSearchItem = {
                id,
                type: "field_property",
                fieldName: searchItem.fieldName,
                propertyDomain: [definitionRecord, "=", definitionRecordId],
                propertyFieldDefinition: definition,
                propertyItemId: searchItem.id,
                description: definitionRecordName
                    ? `${definition.string} (${definitionRecordName})`
                    : definition.string,
                groupId: searchModel.nextGroupId++,
            };
            if (["many2many", "tags"].includes(definition.type)) {
                newSearchItem.operator = "in";
            }
            searchModel.searchItems[id] = newSearchItem;
            searchItemIds.add(id);
        }
    }

    // Items were created/updated outside a query cycle: invalidate the
    // enriched search items memo before reading it back.
    searchModel._enrichedSearchItems = null;
    return searchModel.getSearchItems((searchItem) => searchItemIds.has(searchItem.id));
}

/**
 * Lazily populate search view items for properties fields: fetch definitions
 * via RPC, create group-by items for each, and register them in searchViewFields.
 *
 * @param {SearchModel} searchModel - the SearchModel instance
 */
export async function fillSearchViewItemsProperty(searchModel) {
    if (!searchModel.searchViewFields) {
        return;
    }

    const fields = Object.values(searchModel.searchViewFields);

    for (const field of fields) {
        if (field.type !== "properties") {
            continue;
        }

        const result = await searchModel._fetchPropertiesDefinition(
            searchModel.resModel,
            field.name,
        );

        const searchItemsNames = Object.values(searchModel.searchItems)
            .filter(
                (item) =>
                    item.isProperty && ["groupBy", "dateGroupBy"].includes(item.type),
            )
            .map((item) => item.fieldName);

        for (const {
            definitionRecordId,
            definitionRecordName,
            definitions,
        } of result) {
            // some properties might have been deleted
            const groupNames = definitions.map(
                (definition) => `group_by_${field.name}.${definition.name}`,
            );
            Object.values(searchModel.searchItems).forEach((searchItem) => {
                if (
                    searchItem.isProperty &&
                    searchItem.definitionRecordId === definitionRecordId &&
                    ["groupBy", "dateGroupBy"].includes(searchItem.type) &&
                    !groupNames.includes(searchItem.name)
                ) {
                    // Can't just remove the element (index doubles as id); retype
                    // it instead so it's hidden everywhere until the user refreshes.
                    searchItem.type = "group_by_property_deleted";
                }
            });

            for (const definition of definitions) {
                // Register a fake "field" definition in searchViewFields (type,
                // string, etc.) keyed as "<properties field name>.<property name>".
                const fullName = `${field.name}.${definition.name}`;
                searchModel.searchViewFields[fullName] = {
                    name: fullName,
                    readonly: false,
                    relation: definition.comodel,
                    required: false,
                    searchable: false,
                    selection: definition.selection,
                    sortable: true,
                    store: true,
                    string: definition.string,
                    type: definition.type,
                    relatedPropertyField: field,
                };

                if (
                    !searchItemsNames.includes(fullName) &&
                    !["html", "separator"].includes(definition.type)
                ) {
                    const groupByItem = {
                        description: definition.string,
                        definitionRecordId,
                        definitionRecordName,
                        fieldName: fullName,
                        fieldType: definition.type,
                        isProperty: true,
                        name: `group_by_${field.name}.${definition.name}`,
                        propertyFieldName: field.name,
                        type: ["datetime", "date"].includes(definition.type)
                            ? "dateGroupBy"
                            : "groupBy",
                    };
                    searchModel._createGroupOfSearchItems([groupByItem]);
                }
            }
        }
    }

    // Items may have been soft-deleted (retyped to "group_by_property_deleted")
    // above without going through _createGroupOfSearchItems: invalidate the
    // memo so the Group By menu doesn't list them from a stale snapshot.
    searchModel._enrichedSearchItems = null;
}

/**
 * Fetch property definitions for a given model and field.
 *
 * @param {SearchModel} searchModel - the SearchModel instance
 * @param {string} resModel - the model name
 * @param {string} fieldName - the properties field name
 * @returns {Promise<Object[]>} array of { definitionRecordId, definitionRecordName, definitions }
 */
export async function fetchPropertiesDefinition(searchModel, resModel, fieldName) {
    const domain = [];
    // Read the raw memoized context (the public `context` getter deep-copies
    // on every access); only `active_id` is read here.
    const activeId = searchModel._rawContext.active_id;
    if (activeId) {
        // Assume the active id is the definition record; show only its properties.
        domain.push(["id", "=", activeId]);
    }

    const definitions = await searchModel.fieldService.loadPropertyDefinitions(
        resModel,
        fieldName,
        domain,
    );
    const result = groupBy(
        Object.values(definitions),
        (definition) => definition.record_id,
    );
    return Object.entries(result).map(([recordId, definitions]) => ({
        definitionRecordId: Number.parseInt(recordId, 10),
        definitionRecordName: definitions[0]?.record_name,
        definitions,
    }));
}
