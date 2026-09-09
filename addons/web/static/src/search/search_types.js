// @ts-check
/** @odoo-module native */

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

/** @typedef {SearchItemCommon & { */

/** @typedef {SearchItemCommon & { */

/** @typedef {SearchItemCommon & { */

/** @typedef {SearchItemCommon & { */

/** @typedef {SearchItemCommon & { */

/** @typedef {SearchItemCommon & { */

/** @typedef {SearchItemCommon & { */

/** @typedef {FilterItem | DateFilterItem | GroupByItem | DateGroupByItem */

/** @typedef {SearchItem & { id: number, groupId: number }} StoredSearchItem */

/** @typedef {Record<number, StoredSearchItem>} SearchItems */

/**
 * @typedef {Object} Section
 * @property {number} id
 * @property {string} type
 * @property {Map<any, Object>} values
 * @property {Map<any, Object>} [groups]
 * @property {string} [errorMsg]
 * @property {string} [fieldName]
 * @property {string} [description]
 * @property {boolean} [enableCounters]
 * @property {number} [limit]
 * @property {string} [icon]
 * @property {string} [color]
 * @property {boolean} [expand]
 * @property {string|false} [hierarchize]
 * @property {any} [activeValueId]
 * @property {string} [domain]
 * @property {string|false} [groupBy]
 */

/** @typedef {Section & { type: "category" }} Category */
/** @typedef {Section & { type: "filter" }} Filter */
/** @typedef {(section: Section) => boolean} SectionPredicate */

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

/** @typedef {SearchItem & { */

export {};
