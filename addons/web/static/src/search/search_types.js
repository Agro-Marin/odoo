// @ts-check
/** @odoo-module native */

/** @import { OrderTerm } from "@web/core/utils/order_by" */

/**
 * @typedef {Object} SearchItemCommon
 * @property {number} [id]
 * @property {number} [groupId]
 * @property {number} [groupNumber]
 * @property {string} [description]
 * @property {string} [name]
 * @property {string} [tooltip]
 * @property {string} [invisible]
 * @property {boolean} [isDefault]
 * @property {number} [defaultRank]
 * @property {boolean} [isInvalid]
 */

/**
 * @typedef {SearchItemCommon & {
 *   type: "filter",
 *   domain: string,
 *   context?: string | Record<string, any>,
 * }} FilterItem
 */

/**
 * @typedef {SearchItemCommon & {
 *   type: "dateFilter",
 *   fieldName: string,
 *   fieldType: "date" | "datetime",
 *   domain: string,
 *   optionsParams: PeriodWindow,
 *   defaultGeneratorIds: string[],
 * }} DateFilterItem
 */

/**
 * @typedef {SearchItemCommon & {
 *   type: "groupBy",
 *   fieldName: string,
 *   fieldType?: string,
 *   custom?: boolean,
 *   isProperty?: boolean,
 *   propertyFieldName?: string,
 *   definitionRecordId?: number,
 *   definitionRecordName?: string,
 * }} GroupByItem
 */

/**
 * @typedef {SearchItemCommon & {
 *   type: "dateGroupBy",
 *   fieldName: string,
 *   fieldType?: string,
 *   defaultIntervalId: string,
 *   custom?: boolean,
 *   isProperty?: boolean,
 *   propertyFieldName?: string,
 *   definitionRecordId?: number,
 *   definitionRecordName?: string,
 * }} DateGroupByItem
 */

/**
 * @typedef {SearchItemCommon & {
 *   type: "field",
 *   fieldName: string,
 *   fieldType: string,
 *   domain?: string,
 *   filterDomain?: string,
 *   operator?: string,
 *   context?: string,
 *   defaultAutocompleteValue?: AutocompleteValue,
 * }} FieldItem
 */

/**
 * @typedef {SearchItemCommon & {
 *   type: "field_property",
 *   fieldName: string,
 *   propertyItemId: number,
 *   propertyDomain: any[],
 *   propertyFieldDefinition: Record<string, any>,
 *   operator?: string,
 * }} FieldPropertyItem
 */

/**
 * @typedef {SearchItemCommon & {
 *   type: "favorite",
 *   domain: string,
 *   context: Record<string, any>,
 *   groupBys: string[],
 *   orderBy: OrderTerm[],
 *   userIds: number[],
 *   serverSideId: number,
 *   removable?: boolean,
 * }} FavoriteItem
 */

/**
 * @typedef {FilterItem | DateFilterItem | GroupByItem | DateGroupByItem
 *   | FieldItem | FieldPropertyItem | FavoriteItem} SearchItem
 */

/** @typedef {Record<number, SearchItem>} SearchItems */

/**
 * @typedef {Object} PeriodWindow
 * @property {number} startYear
 * @property {number} endYear
 * @property {number} startMonth
 * @property {number} endMonth
 * @property {{id: string, description: string, domain: string}[]} customOptions
 */

/**
 * @typedef {Object} AutocompleteValue
 * @property {string} label
 * @property {any} value
 * @property {string} operator
 */

/**
 * @typedef {Object} QueryElement
 * @property {number} searchItemId
 * @property {string} [generatorId]
 * @property {string} [intervalId]
 * @property {AutocompleteValue} [autocompleteValue]
 */

/**
 * @typedef {Object} ActiveItem
 * @property {number} searchItemId
 * @property {string[]} [generatorIds]
 * @property {string[]} [intervalIds]
 * @property {AutocompleteValue[]} [autocompleteValues]
 */

/**
 * @typedef {Object} QueryGroup
 * @property {number} id
 * @property {ActiveItem[]} activeItems
 */

/**
 * @typedef {Object} Facet
 * @property {number|symbol} groupId
 * @property {string} [type]
 * @property {string[]} values
 * @property {string} separator
 * @property {string} [title]
 * @property {string} [icon]
 * @property {string} [color]
 * @property {string} [tooltip]
 * @property {string} [domain]
 */

/**
 * @typedef {Object} EnrichedOption
 * @property {string} description
 * @property {string} id
 * @property {number} groupNumber
 * @property {boolean} isActive
 */

/**
 * @typedef {SearchItem & {
 *   isActive: boolean,
 *   options?: EnrichedOption[],
 *   autocompleteValues?: AutocompleteValue[],
 * }} EnrichedSearchItem
 */

export {};
