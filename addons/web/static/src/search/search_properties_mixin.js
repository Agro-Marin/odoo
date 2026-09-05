// @ts-check
/** @odoo-module native */

import { groupBy } from "@web/core/utils/collections/arrays";

import { findGroupByGroupId } from "./search_group_by.js";
import { fireAndForgetNotify } from "./search_notification.js";

/**
 * @param {Record<string, any>} definition
 * @param {string | undefined} definitionRecordName
 * @returns {string}
 */
function propertyDescription(definition, definitionRecordName) {
    return definitionRecordName
        ? `${definition.string} (${definitionRecordName})`
        : definition.string;
}

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
                        existingSearchItem.description = propertyDescription(
                            definition,
                            definitionRecordName,
                        );
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
                        description: propertyDescription(
                            definition,
                            definitionRecordName,
                        ),
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
            if (this._forgetSearchItems(staleIds)) {
                fireAndForgetNotify(this._notify());
            }
            return this.getSearchItems((/** @type {any} */ searchItem) =>
                searchItemIds.has(searchItem.id),
            );
        }

        /**
         * Drop search items the model no longer knows, and whatever the query
         * held on them.
         *
         * @param {number[]} ids
         * @returns {boolean} whether the query lost an element
         */
        _forgetSearchItems(ids) {
            for (const id of ids) {
                delete this.searchItems[id];
            }
            this._enrichedSearchItems = null;
            if (!ids.length) {
                return false;
            }
            const queryLength = this.query.length;
            this.query = this.query.filter(
                (/** @type {any} */ queryElem) => !ids.includes(queryElem.searchItemId),
            );
            return this.query.length !== queryLength;
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

            const prefix = `${field.name}.`;
            for (const fieldName of Object.keys(this.searchViewFields)) {
                if (fieldName.startsWith(prefix) && !liveFieldNames.has(fieldName)) {
                    delete this.searchViewFields[fieldName];
                }
            }

            if (this._forgetSearchItems(staleIds)) {
                await this._notify();
            }
        }

        /**
         * @param {string} resModel
         * @param {string} fieldName
         * @returns {Promise<{definitionRecordId: number, definitionRecordName: string, definitions: Record<string, any>[]}[]>}
         */
        async _fetchPropertiesDefinition(resModel, fieldName) {
            const domain = [];
            const activeId = this.globalContext.active_id;
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
