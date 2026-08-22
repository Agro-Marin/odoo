// @ts-check
/** @odoo-module native */

import { groupBy } from "@web/core/utils/collections/arrays";

import { findGroupByGroupId } from "./search_group_by.js";
import { fireAndForgetNotify } from "./search_notification.js";

/**
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchPropertiesMixin = (Base) =>
    class extends Base {
        /**
         * @param {Record<string, any>} searchItem
         * @returns {Promise<Object[]>}
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
            /** @type {Record<string, any>} */
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
                    /** @type {Record<string, any>} */
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

            const staleIds = Object.values(existingFieldProperties)
                .filter((/** @type {any} */ item) => !searchItemIds.has(item.id))
                .map((/** @type {any} */ item) => item.id);
            for (const id of staleIds) {
                delete this.searchItems[id];
            }
            this._enrichedSearchItems = null;
            if (staleIds.length) {
                const queryLength = this.query.length;
                this.query = this.query.filter(
                    (/** @type {any} */ queryElem) =>
                        !staleIds.includes(queryElem.searchItemId),
                );
                if (this.query.length !== queryLength) {
                    fireAndForgetNotify(this._notify());
                }
            }
            return this.getSearchItems((/** @type {any} */ searchItem) =>
                searchItemIds.has(searchItem.id),
            );
        }

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
         * @param {Record<string, any>} field
         */
        async _fillPropertyFieldSearchItems(field) {
            const result = await this._fetchPropertiesDefinition(
                this.resModel,
                field.name,
            );

            const isPropertyGroupBy = (/** @type {any} */ item) =>
                item.isProperty && ["groupBy", "dateGroupBy"].includes(item.type);
            const existingByFieldName = new Map(
                Object.values(this.searchItems)
                    .filter(isPropertyGroupBy)
                    .map((/** @type {any} */ item) => [item.fieldName, item]),
            );
            const liveIds = new Set();
            const liveFieldNames = new Set();
            let groupByGroupId = findGroupByGroupId(this.searchItems);

            for (const {
                definitionRecordId,
                definitionRecordName,
                definitions,
            } of result) {
                for (const definition of definitions) {
                    const fullName = `${field.name}.${definition.name}`;
                    liveFieldNames.add(fullName);
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

                    if (["html", "separator"].includes(definition.type)) {
                        continue;
                    }
                    const existing = existingByFieldName.get(fullName);
                    if (existing) {
                        liveIds.add(existing.id);
                        continue;
                    }
                    const id = this.nextId++;
                    this.searchItems[id] = {
                        id,
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
                        groupId: (groupByGroupId ??= this.nextGroupId++),
                    };
                    liveIds.add(id);
                }
            }

            const staleIds = Object.values(this.searchItems)
                .filter(
                    (/** @type {any} */ item) =>
                        isPropertyGroupBy(item) &&
                        item.propertyFieldName === field.name &&
                        !liveIds.has(item.id),
                )
                .map((/** @type {any} */ item) => item.id);
            for (const id of staleIds) {
                delete this.searchItems[id];
            }

            const prefix = `${field.name}.`;
            for (const fieldName of Object.keys(this.searchViewFields)) {
                if (fieldName.startsWith(prefix) && !liveFieldNames.has(fieldName)) {
                    delete this.searchViewFields[fieldName];
                }
            }

            this._enrichedSearchItems = null;
            if (staleIds.length) {
                const queryLength = this.query.length;
                this.query = this.query.filter(
                    (/** @type {any} */ queryElem) =>
                        !staleIds.includes(queryElem.searchItemId),
                );
                if (this.query.length !== queryLength) {
                    await this._notify();
                }
            }
        }

        /**
         * @param {string} resModel
         * @param {string} fieldName
         * @returns {Promise<{definitionRecordId: number, definitionRecordName: string, definitions: Record<string, any>[]}[]>}
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
