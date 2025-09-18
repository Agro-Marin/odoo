// @ts-check

/**
 * @module @web/model/types - Shared type definitions for ORM field metadata and search parameters
 *
 * These types describe the shape of field definitions and view parameters
 * used across model/, search/, and views/ layers.
 */

/** @import { Context } from "@web/core/context" */
/** @import { DomainListRepr } from "@web/core/domain" */
/** @import { OrderTerm } from "@web/core/utils/order_by" */

/**
 * @typedef {{
 *  name: string;
 *  type: string;
 *  selection?: [string | number, string][];
 *  relation?: string;
 *  relation_field?: string;
 *  relatedPropertyField?: string;
 *  definition_record?: string;
 *  definition_record_field?: string;
 *  context?: Context | string;
 *  domain?: DomainListRepr | string;
 *  currency_field?: string;
 *  falsy_value_label?: string;
 *  string?: string;
 *  readonly?: boolean;
 *  required?: boolean;
 *  searchable?: boolean;
 *  sortable?: boolean;
 *  store?: boolean;
 *  groupable?: boolean;
 *  aggregator?: string;
 *  [key: string]: any;
 * }} Field
 *
 * @typedef {{
 *  context: Context | string;
 *  forceSave?: boolean;
 *  invisible: string;
 *  isHandle?: boolean;
 *  onChange: boolean;
 *  readonly: string;
 *  required: string;
 *  related?: { activeFields: Record<string, FieldInfo>; fields: Record<string, Field> };
 *  limit?: number;
 *  defaultOrderBy?: OrderTerm[];
 *  relatedPropertyField?: string;
 *  [key: string]: any;
 * }} FieldInfo
 *
 * @typedef {{
 *  context: Context;
 *  domain: DomainListRepr;
 *  groupBy: string[];
 *  orderBy: OrderTerm[];
 *  resModel: string;
 *  resId?: number | false;
 *  resIds?: number[];
 *  useSampleModel?: boolean;
 *  [key: string]: any;
 * }} SearchParams
 */
