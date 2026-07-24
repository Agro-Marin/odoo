// @ts-check
/** @odoo-module native */

/** @module @web/search/search_properties_mixin - Property-field search logic mixed into SearchModel */

import { groupBy } from "@web/core/utils/collections/arrays";

/**
 * Property-field search logic for SearchModel: lazily loading property
 * definitions and materializing the corresponding search / group-by items.
 *
 * Mixed into SearchModel (``extends SearchPropertiesMixin(...)``) rather than
 * kept as pass-``this`` module functions with proxy methods: the logic lives on
 * the prototype directly, using ``this``. None of these methods is overridden by
 * any SearchModel subclass. ``searchViewFields``/``searchItems``/``fieldService``
 * and the item helpers live on SearchModel and are reached via ``this``.
 *
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchPropertiesMixin = (Base) =>
    class extends Base {
        /**
         * Generate (or refresh) property-based search items for a "properties" field.
         *
         * @param {Object} searchItem - a "field" search item with fieldType "properties"
         * @returns {Promise<Object[]>} matching search items
         */
        async getSearchItemsProperties(searchItem) {
            if (searchItem.type !== "field" || searchItem.fieldType !== "properties") {
                return [];
            }
            const field = this.searchViewFields[searchItem.fieldName];
            const definitionRecord = field.definition_record;
            const result = await this._fetchPropertiesDefinition(
                this.resModel,
                searchItem.fieldName,
            );

            const searchItemIds = new Set();
            const existingFieldProperties = {};
            for (const item of Object.values(this.searchItems)) {
                if (
                    item.type === "field_property" &&
                    item.propertyItemId === searchItem.id
                ) {
                    existingFieldProperties[item.propertyFieldDefinition.name] = item;
                }
            }

            for (const {
                definitionRecordId,
                definitionRecordName,
                definitions,
            } of result) {
                for (const definition of definitions) {
                    if (definition.type === "separator") {
                        continue;
                    }
                    const existingSearchItem = existingFieldProperties[definition.name];
                    if (existingSearchItem) {
                        // Already in the list (e.g. unfold properties, edit in a form,
                        // come back): the label may have changed, so refresh it.
                        existingSearchItem.description = `${definition.string} (${definitionRecordName})`;
                        searchItemIds.add(existingSearchItem.id);
                        continue;
                    }
                    const id = this.nextId++;
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
                        groupId: this.nextGroupId++,
                    };
                    if (["many2many", "tags"].includes(definition.type)) {
                        newSearchItem.operator = "in";
                    }
                    this.searchItems[id] = newSearchItem;
                    searchItemIds.add(id);
                }
            }

            // Items were created/updated outside a query cycle: invalidate the
            // enriched search items memo before reading it back.
            this._enrichedSearchItems = null;
            return this.getSearchItems((searchItem) =>
                searchItemIds.has(searchItem.id),
            );
        }

        /**
         * Lazily populate search view items for properties fields: fetch definitions
         * via RPC, create group-by items for each, register them in searchViewFields.
         */
        async fillSearchViewItemsProperty() {
            if (!this.searchViewFields) {
                return;
            }

            const fields = Object.values(this.searchViewFields);

            // One PropertiesGroupByItem component exists per properties field, and
            // each calls this (unscoped) routine once on first open. Without a
            // cross-call guard, N components x N fields => N^2 property-definition
            // RPCs. Memoize the in-flight/settled fill promise per properties field
            // on the SearchModel instance so each field is fetched and turned into
            // search items at most once, regardless of how many components trigger
            // the fill — and so a caller that arrives while a fill is still in flight
            // awaits the SAME load instead of returning early with zero items (which
            // would latch an empty Properties group-by for the session). A failed
            // fill is evicted from the memo so a later open can retry.
            /** @type {Map<string, Promise<void>>} */
            const filledPropertyFields = (this._filledPropertyFields ??= new Map());

            const proms = [];
            for (const field of fields) {
                if (field.type !== "properties") {
                    continue;
                }
                let prom = filledPropertyFields.get(field.name);
                if (!prom) {
                    prom = this._fillPropertyFieldSearchItems(field);
                    prom.catch(() => {
                        if (filledPropertyFields.get(field.name) === prom) {
                            filledPropertyFields.delete(field.name);
                        }
                    });
                    filledPropertyFields.set(field.name, prom);
                }
                proms.push(prom);
            }
            await Promise.all(proms);
        }

        /**
         * Fetch one properties field's definitions and materialize its group-by
         * search items (single-flight body of {@link fillSearchViewItemsProperty}).
         *
         * @param {Object} field - a searchViewFields entry with type "properties"
         */
        async _fillPropertyFieldSearchItems(field) {
            const result = await this._fetchPropertiesDefinition(
                this.resModel,
                field.name,
            );

            const searchItemsNames = Object.values(this.searchItems)
                .filter(
                    (item) =>
                        item.isProperty &&
                        ["groupBy", "dateGroupBy"].includes(item.type),
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
                Object.values(this.searchItems).forEach((searchItem) => {
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
                    this.searchViewFields[fullName] = {
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
                        this._createGroupOfSearchItems([groupByItem]);
                    }
                }
            }

            // Items may have been soft-deleted (retyped to "group_by_property_deleted")
            // above without going through _createGroupOfSearchItems: invalidate the
            // memo so the Group By menu doesn't list them from a stale snapshot.
            this._enrichedSearchItems = null;
        }

        /**
         * Fetch property definitions for a given model and field.
         *
         * @param {string} resModel - the model name
         * @param {string} fieldName - the properties field name
         * @returns {Promise<Object[]>} array of { definitionRecordId, definitionRecordName, definitions }
         */
        async _fetchPropertiesDefinition(resModel, fieldName) {
            const domain = [];
            // Read the raw memoized context (the public `context` getter deep-copies
            // on every access); only `active_id` is read here.
            const activeId = this._rawContext.active_id;
            if (activeId) {
                // Assume the active id is the definition record; show only its properties.
                domain.push(["id", "=", activeId]);
            }

            const definitions = await this.fieldService.loadPropertyDefinitions(
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
    };
