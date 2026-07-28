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

            // A definition deleted on the parent record leaves its search item
            // behind, and an active one keeps contributing its clause to the
            // effective domain — the user goes on searching a property that no
            // longer exists. `_fillPropertyFieldSearchItems` already retires
            // vanished group-bys; do the same for the field_property items.
            const staleIds = Object.values(existingFieldProperties)
                .filter((item) => !searchItemIds.has(item.id))
                .map((item) => item.id);
            for (const id of staleIds) {
                delete this.searchItems[id];
            }
            this._enrichedSearchItems = null;
            if (staleIds.length) {
                const queryLength = this.query.length;
                this.query = this.query.filter(
                    (queryElem) => !staleIds.includes(queryElem.searchItemId),
                );
                if (this.query.length !== queryLength) {
                    this._notify();
                }
            }
            return this.getSearchItems((searchItem) =>
                searchItemIds.has(searchItem.id),
            );
        }

        /**
         * Lazily populate search view items for properties fields: fetch definitions
         * via RPC, create group-by items for each, register them in searchViewFields.
         *
         * Concurrent calls for one field share a single fetch, but the entry is
         * dropped once it settles rather than memoised for the model's lifetime:
         * definitions live on the parent record and change under us (a property
         * added, renamed or deleted), and `_fillPropertyFieldSearchItems` is
         * idempotent, so re-running it is how those changes reach the Group By
         * menu. The only call site is one dropdown open, so this costs at most
         * one RPC per open.
         */
        async fillSearchViewItemsProperty() {
            if (!this.searchViewFields) {
                return;
            }

            const fields = Object.values(this.searchViewFields);

            /** @type {Map<string, Promise<void>>} */
            const inFlight = (this._filledPropertyFields ??= new Map());

            const proms = [];
            for (const field of fields) {
                if (field.type !== "properties") {
                    continue;
                }
                let prom = inFlight.get(field.name);
                if (!prom) {
                    prom = this._fillPropertyFieldSearchItems(field);
                    prom.catch(() => {}).finally(() => {
                        if (inFlight.get(field.name) === prom) {
                            inFlight.delete(field.name);
                        }
                    });
                    inFlight.set(field.name, prom);
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
                        searchItem.type = "group_by_property_deleted";
                    }
                });

                for (const definition of definitions) {
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
            const activeId = this._rawContext.active_id;
            if (activeId) {
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
