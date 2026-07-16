// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_model - Pivot table data loading, group tree expansion, measure aggregation, and cell computation */

import {
    cartesian,
    sections,
    symmetricalDifference,
} from "@web/core/utils/collections/arrays";
import { KeepLast, Mutex, Race } from "@web/core/utils/concurrency";
import { addPropertyFieldDefs, Model } from "@web/model/model";
import { DEFAULT_INTERVAL } from "@web/search/utils/dates";
import {
    computeReportMeasures,
    dropUnknownMeasures,
    processMeasure,
} from "@web/views/view_measurements";

import { aggregateSubdivisions } from "./pivot_aggregation.js";
import { computeExportedTableWidth, formatPivotForExport } from "./pivot_export.js";
import {
    findGroup,
    getLeafCounts,
    getTreeHeight,
    hasData,
    pruneTree,
    sortTree,
    stripSortedKeys,
} from "./pivot_group_tree.js";
import { getCellValue, getMeasureSpecs, makeCellKey } from "./pivot_measurements.js";
import { getTableHeaders, getTableRows } from "./pivot_table.js";
import { getGroupBySpecs, getGroupDomain } from "./pivot_value_utils.js";

/**
 * Pivot Model
 *
 * The pivot model keeps an in-memory representation of the pivot table shown on
 * screen. A pivot table is at its core a 2-dimensional object with a 'list'
 * component: rows/cols can be expanded to zoom into the structure. It presents
 * aggregated values for various groups of records in one domain.
 *
 * Let us consider a simple example and let us fix the vocabulary:
 * __________________________________________________________________________
 * |                    |   Total                                           |
 * |                    |___________________________________________________|
 * |                    |   Sale Team 1   |  Sale Team 2   |                |
 * |                    |_________________|________________|________________|
 * |                    |   Sales total   |  Sales total   |  Sales total   |
 * |____________________|_________________|________________|________________|
 * | Total              |      110        |       30       |      140       |
 * |    Europe          |       35        |       30       |       65       |
 * |        Brussels    |       15        |       30       |       45       |
 * |        Paris       |       20        |        0       |       20       |
 * |    North America   |       75        |                |       75       |
 * |        Washington  |       75        |                |       75       |
 * |____________________|_________________|________________|________________|
 *
 *
 * META DATA:
 *
 * In the above pivot table, the records have been grouped using the fields
 *
 *      continent_id, city_id
 *
 * for rows and
 *
 *      sale_team_id
 *
 * for columns.
 *
 * The measure is the field 'sales_total'.
 *
 * The domain considered is 'sale_date in June 2020'.
 *
 * In the model,
 *
 *      - rowGroupBys is the list [continent_id, city_id]
 *      - colGroupBys is the list [sale_team_id]
 *      - measures is the list [sales_total]
 *      - domain is the domain expression for say sale_date in June 2020:
 *          [['sale_date', >=, 2020-06-01], ['sale_date', '<=', 2020-06-30]]
 *
 * DATA:
 *
 * Recall that a group is constituted by records that have the same (raw) values
 * for a list of fields. Thus the group itself is identified by this list.
 *
 * In the above table, the following groups are found:
 *
 *      the 'row groups'
 *      - Total
 *      - Europe
 *      - America
 *      - Europe, Brussels
 *      - Europe, Paris
 *      - America, Washington
 *
 *      the 'col groups'
 *
 *      - Total
 *      - Sale Team 1
 *      - Sale Team 2
 *
 *      and all non trivial combinations of row groups and col groups
 *
 *      - Europe, Sale Team 1
 *      - Europe, Brussels, Sale Team 2
 *      - America, Washington, Sale Team 1
 *      - ...
 *
 * The list of fields is created from the concatenation of two lists of fields, the first in
 *
 * [], [f1], [f1, f2], ... [f1, f2, ..., fn]  for [f1, f2, ..., fn] the full list of groupbys
 * (called rowGroupBys) used to create row groups
 *
 * In the example: [], [continent_id], [continent_id, city_id].
 *
 * and the second in
 * [], [g1], [g1, g2], ... [g1, g2, ..., gm]  for [g1, g2, ..., gm] the full list of groupbys
 * (called colGroupBys) used to create col groups.
 *
 * In the example: [], [sale_team_id].
 *
 * Thus there are (n+1)*(m+1) lists of fields possible.
 *
 * In the example: 6 lists possible, namely [],
 *                                          [continent_id], [sale_team_id],
 *                                          [continent_id, sale_team_id], [continent_id, city_id],
 *                                          [continent_id, city_id, sale_team_id]
 *
 * A given list is thus of the form [f1,..., fi, g1,..., gj] or better [[f1,...,fi], [g1,...,gj]]
 *
 * For each list of fields possible, one read_group is done
 * and gives results of the form (an exception for list [])
 *
 * g = {
 *  f1: v1, ..., fi: vi,
 *  g1: w1, ..., gj: wj,
 *  m1: x1, ..., mk: xk,
 *  __count: c,
 *  __domain: d
 * }
 *
 * where v1,...,vi,w1,...,Wj are 'values' for the corresponding fields and
 * m1,...,mk are the fields selected as measures.
 *
 * For example, g = {
 *      continent_id: [1, 'Europe']
 *      sale_team_id: [1, 'Sale Team 1']
 *      sales_count: 25,
 *      __count: 4
 *      __domain: [
 *                  ['sale_date', >=, 2020-06-01], ['sale_date', '<=', 2020-06-30],
 *                  ['continent_id', '=', 1],
 *                  ['sale_team_id', '=', 1]
 *                ]
 * }
 *
 * Thus the above group g is fully determined by [[v1,...,vi], [w1,...,wj]].
 *
 * When j=0, g corresponds to a row group (or also row header) and is of the form [[v1,...,vi], []] or more simply [v1,...vi]
 * (not forgetting the list [v1,...vi] comes from left).
 * When i=0, g corresponds to a col group (or col header) and is of the form [[], [w1,...,wj]] or more simply [w1,...,wj].
 *
 * A generic group g as above [[v1,...,vi], [w1,...,wj]] corresponds to the two headers [[v1,...,vi], []]
 * and [[], [w1,...,wj]].
 *
 * Here is a description of the data structure manipulated by the pivot model.
 *
 * Five objects contain all the data from the read_groups
 *
 *      - rowGroupTree: contains information on row headers
 *             the nodes correspond to the groups of the form [[v1,...,vi], []]
 *             The root is [[], []].
 *             A node [[v1,...,vl], []] has as direct children the nodes of the form [[v1,...,vl,v], []],
 *             this means that a direct child is obtained by grouping records using the single field fi+1
 *
 *             The structure at each level is of the form
 *
 *             {
 *                  root: {
 *                      values: [v1,...,vl],
 *                      labels: [label1,...,labedll]
 *                  },
 *                  directSubTrees: {
 *                      v => {
 *                              root: {
 *                                  values: [v1,...,vl,v]
 *                                  labels: [label1,...,labell,label]
 *                              },
 *                              directSubTrees: {...}
 *                          },
 *                      v' => {...},
 *                      ...
 *                  }
 *             }
 *
 *             (directSubTrees is a Map instance)
 *
 *             In the example, the rowGroupTree is:
 *
 *             {
 *                  root: {
 *                      values: [],
 *                      labels: []
 *                  },
 *                  directSubTrees: {
 *                      1 => {
 *                              root: {
 *                                  values: [1],
 *                                  labels: ['Europe'],
 *                              },
 *                              directSubTrees: {
 *                                  1 => {
 *                                          root: {
 *                                              values: [1, 1],
 *                                              labels: ['Europe', 'Brussels'],
 *                                          },
 *                                          directSubTrees: new Map(),
 *                                  },
 *                                  2 => {
 *                                          root: {
 *                                              values: [1, 2],
 *                                              labels: ['Europe', 'Paris'],
 *                                          },
 *                                          directSubTrees: new Map(),
 *                                  },
 *                              },
 *                          },
 *                      2 => {
 *                              root: {
 *                                  values: [2],
 *                                  labels: ['America'],
 *                              },
 *                              directSubTrees: {
 *                                  3 => {
 *                                          root: {
 *                                              values: [2, 3],
 *                                              labels: ['America', 'Washington'],
 *                                          }
 *                                          directSubTrees: new Map(),
 *                                  },
 *                              },
 *                      },
 *                  },
 *             }
 *
 *      - colGroupTree: contains information on col headers
 *              The same as above with right instead of left
 *
 *      - measurements: contains information on measure values for all the groups
 *
 *              the object keys are of the form JSON.stringify([[v1,...,vi], [w1,...,wj]])
 *              and objects values are of the form {m1: x1,...,mk: xk}
 *              The structure looks like
 *
 *              {
 *                  JSON.stringify([[], []]): {m1: x1,...,mk: xk}
 *                  ....
 *                  JSON.stringify([[v1,...,vi], [w1,...,wj]]): {m1: y1,...,mk: yk},
 *                  ....
 *                  JSON.stringify([[v1,...,vn], [w1,...,wm]]): {m1: z1,...,mk: zk},
 *              }
 *              Thus the structure contains all information for all groups on measure values.
 *
 *
 *              this.measurments["[[], []]"]['foo'] gives the value of the measure 'foo' for the group 'Total'.
 *
 *              In the example:
 *                  {
 *                      "[[], []]": {'sales_total': 140}           (total/total)
 *                      ...
 *                      "[[1, 2], [2]]": {'sales_total': 0}        (Europe/Paris/Sale Team 2)
 *                      ...
 *                  }
 *
 *      - counts: contains information on the number of records in each groups
 *              The structure is similar to the above but the values are numbers (counts)
 *      - groupDomains:
 *              The structure is similar to the above but the values are domains
 *
 *      With this light data structures, all manipulation done by the model are eased and redundancies are limited.
 *      Each time a rendering or an export of the data has to be done, the pivot table is generated by the getTable function.
 */

/**
 * @typedef Meta
 * @property {string[]} activeMeasures
 * @property {string[]} colGroupBys
 * @property {boolean} disableLinking
 * @property {Object} fields
 * @property {Object} measures
 * @property {string} resModel
 * @property {string[]} rowGroupBys
 * @property {string} title
 * @property {boolean} useSampleModel
 * @property {Object} widgets
 * @property {Map} customGroupBys
 * @property {string[]} expandedRowGroupBys
 * @property {string[]} expandedColGroupBys
 * @property {Object} sortedColumn
 * @property {Array} domain
 */

/**
 * @typedef Data
 * @property {Object} colGroupTree
 * @property {Object} rowGroupTree
 * @property {Object} groupDomains
 * @property {Object} measurements
 * @property {Object} currencyIds
 * @property {Object} counts
 * @property {Object} numbering
 */

/**
 * @typedef {import("@web/model/types").SearchParams} SearchParams
 */

/**
 * @typedef Config
 * @property {any} metaData
 * @property {any} data
 */

/**
 * Sentinel resolved by ``_keepLastAdd`` when the awaited request was
 * superseded by a newer one (see the concurrency policy on PivotModel).
 */
const SUPERSEDED = Symbol("superseded");

export class PivotModel extends Model {
    // The renderer subscribes to notify() itself via useReactiveModel;
    // the legacy deep-render bus listener is not needed (model.js).
    static reactiveRenderers = true;

    /**
     * @override
     * @param {Object} params
     * @param {Object} params.metaData
     * @param {string[]} params.metaData.activeMeasures
     * @param {string[]} params.metaData.colGroupBys
     * @param {Object} params.metaData.fields
     * @param {Object[]} params.metaData.measures
     * @param {string} params.metaData.resModel
     * @param {string[]} params.metaData.rowGroupBys
     * @param {string|null} params.metaData.defaultOrder
     * @param {boolean} params.metaData.disableLinking
     * @param {boolean} params.metaData.useSampleModel
     * @param {Map} [params.metaData.customGroupBys={}]
     * @param {string[]} [params.metaData.expandedColGroupBys=[]]
     * @param {string[]} [params.metaData.expandedRowGroupBys=[]]
     * @param {Object|null} [params.metaData.sortedColumn=null]
     * @param {Object} [params.data] previously exported data
     */
    setup(params) {
        // Concurrency policy
        // ------------------
        // Two interaction classes, two behaviours:
        //
        // - LOADS (load, expandAll, toggleMeasure) rebuild the whole table.
        //   They go through `this.race` + `this.keepLast`: last one wins, an
        //   in-flight load is silently superseded.
        // - STRUCTURE MUTATIONS (expandGroup, addGroupBy, closeGroup) refine
        //   the current table. They QUEUE on `this.expandMutex` so
        //   back-to-back clicks are never lost and never interleave (a close
        //   running mid-expansion would pull tree nodes from under
        //   _prepareData).
        //
        // Across classes: every entry point DROPS the interaction while a
        // load is in flight (`race.getCurrentProm()`), because it targets a
        // table about to be replaced ("sort rows while loading a filter" &
        // co. pin this); queued mutations re-check that guard when they
        // dequeue, so they never clobber a load that started while they
        // waited. Conversely a load fired while a mutation's RPC is pending
        // supersedes it: the mutexed callback then settles with SUPERSEDED
        // and discards its result (see _keepLastAdd) instead of hanging the
        // mutex queue forever, as a bare KeepLast.add would.
        // sortRows is synchronous and only race-guarded (no RPC).
        this.keepLast = new KeepLast();
        this.race = new Race();
        this.expandMutex = new Mutex();
        /** @type {((value: typeof SUPERSEDED) => void)[]} */
        this._supersessionWatchers = [];
        /** @type {(...args: any[]) => any} */
        const _loadData = this._loadData.bind(this);
        /** @type {any} */
        this._loadData = (...args) => this.race.add(_loadData(...args));

        let sortedColumn = params.metaData.sortedColumn || null;
        if (!sortedColumn && params.metaData.defaultOrder) {
            const defaultOrder = params.metaData.defaultOrder.split(" ");
            sortedColumn = {
                groupId: [[], []],
                measure: defaultOrder[0],
                order: defaultOrder[1] ? defaultOrder[1] : "asc",
            };
        }

        this.searchParams = {
            context: {},
            domain: [],
            groupBy: [],
        };
        this.data = params.data || {
            colGroupTree: null,
            rowGroupTree: null,
            groupDomains: {},
            measurements: {},
            currencyIds: {},
            counts: {},
            numbering: {},
        };
        const metaData = {
            ...params.metaData,
            customGroupBys: params.metaData.customGroupBys || new Map(),
            expandedRowGroupBys: params.metaData.expandedRowGroupBys || [],
            expandedColGroupBys: params.metaData.expandedColGroupBys || [],
            sortedColumn,
        };
        this.metaData = this._buildMetaData(metaData);

        this.reload = false; // used to discriminate between the first load and subsequent reloads
        this.lastPivotMeasuresKey = undefined; // last consumed context.pivot_measures (JSON), for change detection
        this.nextActiveMeasures = null; // allows to toggle several measures consecutively
    }

    //--------------------------------------------------------------------------
    // Public
    //--------------------------------------------------------------------------

    /**
     * Add a groupBy to rowGroupBys or colGroupBys according to provided type.
     *
     * @param {Object} params
     * @param {Array[]} params.groupId
     * @param {string} params.fieldName
     * @param {'row'|'col'} params.type
     * @param {boolean} [params.custom=false]
     * @param {string} [params.interval]
     */
    async addGroupBy(params) {
        if (this.race.getCurrentProm()) {
            return; // we are currently reloading the table
        }

        const { groupId, fieldName, type, custom } = params;
        let { interval } = params;
        await this.expandMutex.exec(async () => {
            if (this.race.getCurrentProm()) {
                return; // a reload started while queued: it replaces the table
            }
            const metaData = this._buildMetaData();
            if (custom && !metaData.customGroupBys.has(fieldName)) {
                const field = metaData.fields[fieldName];
                if (!interval && ["date", "datetime"].includes(field.type)) {
                    interval = DEFAULT_INTERVAL;
                }
                metaData.customGroupBys.set(fieldName, {
                    ...field,
                    id: fieldName,
                });
            }

            let groupBy = fieldName;
            if (interval) {
                groupBy = `${groupBy}:${interval}`;
            }
            if (type === "row") {
                metaData.expandedRowGroupBys.push(groupBy);
            } else {
                metaData.expandedColGroupBys.push(groupBy);
            }
            const config = { metaData, data: this.data };
            if (!(await this._expandGroup(groupId, type, config))) {
                return; // superseded by a reload: the table was replaced
            }
            // Merge only THIS mutation's delta (customGroupBys + expanded
            // groupBys) into the CURRENT metaData: while the expansion RPC was
            // in flight, an interleaved toggleMeasure (remove path) may have
            // replaced this.metaData and an interleaved sortRows may have
            // mutated its sortedColumn — both run outside the expandMutex.
            // Assigning the pre-RPC snapshot wholesale here used to resurrect
            // the removed measure / the stale sort indicator.
            const mergedMetaData = this._buildMetaData();
            mergedMetaData.customGroupBys = metaData.customGroupBys;
            mergedMetaData.expandedRowGroupBys = metaData.expandedRowGroupBys;
            mergedMetaData.expandedColGroupBys = metaData.expandedColGroupBys;
            if (mergedMetaData.sortedColumn) {
                // aggregateSubdivisions re-sorted the tree with the SNAPSHOT's
                // sortedColumn; re-apply the current one so the row order
                // matches the indicator (idempotent when they are the same).
                this._sortRows(mergedMetaData.sortedColumn, {
                    metaData: mergedMetaData,
                    data: this.data,
                });
            }
            this.metaData = mergedMetaData;
            this.notify();
        });
    }
    /**
     * Close the group with id given by groupId.
     *
     * @param {Array[]} groupId
     * @param {'row'|'col'} type
     */
    async closeGroup(groupId, type) {
        if (this.race.getCurrentProm()) {
            return; // we are currently reloading the table
        }

        await this.expandMutex.exec(() => {
            if (this.race.getCurrentProm()) {
                return; // a reload started while queued: it replaces the table
            }
            let groupBys;
            let expandedGroupBys;
            let keyPart;
            let group;
            let tree;
            if (type === "row") {
                groupBys = this.metaData.rowGroupBys;
                expandedGroupBys = this.metaData.expandedRowGroupBys;
                tree = this.data.rowGroupTree;
                group = findGroup(this.data.rowGroupTree, groupId[0]);
                keyPart = 0;
            } else {
                groupBys = this.metaData.colGroupBys;
                expandedGroupBys = this.metaData.expandedColGroupBys;
                tree = this.data.colGroupTree;
                group = findGroup(this.data.colGroupTree, groupId[1]);
                keyPart = 1;
            }
            if (!group) {
                return; // a queued mutation already removed this group
            }

            const groupIdPart = groupId[keyPart];
            const range = groupIdPart.map((_, index) => index);
            // The four cell maps share the same key set (see
            // aggregateSubdivisions): parse and evaluate each key once
            // instead of once per map.
            const keepByKey = new Map();
            function keep(key) {
                let kept = keepByKey.get(key);
                if (kept === undefined) {
                    const idPart = JSON.parse(key)[keyPart];
                    kept =
                        range.some((index) => groupIdPart[index] !== idPart[index]) ||
                        idPart.length === groupIdPart.length;
                    keepByKey.set(key, kept);
                }
                return kept;
            }
            function omitKeys(object) {
                const newObject = {};
                for (const key of Object.keys(object)) {
                    if (keep(key)) {
                        newObject[key] = object[key];
                    }
                }
                return newObject;
            }
            this.data.measurements = omitKeys(this.data.measurements);
            this.data.currencyIds = omitKeys(this.data.currencyIds);
            this.data.counts = omitKeys(this.data.counts);
            this.data.groupDomains = omitKeys(this.data.groupDomains);

            group.directSubTrees.clear();
            delete group.sortedKeys;
            const newGroupBysLength = getTreeHeight(tree) - 1;
            if (newGroupBysLength <= groupBys.length) {
                expandedGroupBys.splice(0);
                groupBys.splice(newGroupBysLength);
            } else {
                expandedGroupBys.splice(newGroupBysLength - groupBys.length);
            }
            this.notify();
        });
    }
    /**
     * Reload the view with the current rowGroupBys and colGroupBys.
     */
    async expandAll() {
        if (this.race.getCurrentProm()) {
            return; // a load is already in flight (matches expandGroup/sortRows/addGroupBy)
        }
        const config = { metaData: this.metaData, data: this.data };
        await this._loadData(config, false);
        this.notify();
    }
    /**
     * Expand a group by using groupBy to split it and trigger a re-rendering.
     *
     * @param {string} groupId
     * @param {'row'|'col'} type
     */
    async expandGroup(groupId, type) {
        if (this.race.getCurrentProm()) {
            return; // we are currently reloading the table
        }

        await this.expandMutex.exec(async () => {
            if (this.race.getCurrentProm()) {
                return; // a reload started while queued: it replaces the table
            }
            const config = { metaData: this.metaData, data: this.data };
            if (await this._expandGroup(/** @type {any} */ (groupId), type, config)) {
                this.notify();
            }
        });
    }
    /**
     * Export model data in a form suitable for an easy encoding of the pivot
     * table in excell.
     *
     * @returns {Object}
     */
    exportData() {
        return formatPivotForExport(this.getTable(), this.metaData);
    }
    /**
     * Swap the pivot columns and the rows.
     */
    async flip() {
        // Wait for any in-flight LOAD, then transpose the resulting table
        // (unlike closeGroup, flip stays meaningful across a load, so it
        // defers rather than drops — pinned by "flip axis while loading").
        await this.race.getCurrentProm();
        // ...but also serialize with STRUCTURE MUTATIONS on the expandMutex:
        // expandGroup/addGroupBy run their RPCs under expandMutex (untracked
        // by `this.race`), so an expansion landing mid-flip would write
        // UNTWISTED [rowValues, colValues] keys into the already-swapped trees,
        // corrupting cells until the next full load.
        await this.expandMutex.exec(async () => {
            // A load may have started while we were queued on the mutex; wait
            // it out too so we transpose the freshest table, not a stale one.
            await this.race.getCurrentProm();
            // swap the data: the main column and the main row
            let temp = this.data.rowGroupTree;
            this.data.rowGroupTree = this.data.colGroupTree;
            this.data.colGroupTree = temp;

            // The transposed trees carry sortedKeys computed against their
            // pre-flip axis; the sort no longer applies (sortedColumn is reset
            // below), and leaving them stale would make a later expand render
            // no children (sortedKeys iterated instead of the fresh Map keys).
            stripSortedKeys(this.data.rowGroupTree);
            stripSortedKeys(this.data.colGroupTree);

            // we need to update the record metaData: (expanded) row and col groupBys
            temp = this.metaData.rowGroupBys;
            this.metaData.rowGroupBys = this.metaData.colGroupBys;
            this.metaData.colGroupBys = temp;
            temp = this.metaData.expandedColGroupBys;
            this.metaData.expandedColGroupBys = this.metaData.expandedRowGroupBys;
            this.metaData.expandedRowGroupBys = temp;

            function twistKey(key) {
                return JSON.stringify(JSON.parse(key).reverse());
            }

            function twist(object) {
                const newObject = {};
                for (const key of Object.keys(object)) {
                    newObject[twistKey(key)] = object[key];
                }
                return newObject;
            }

            this.data.measurements = twist(this.data.measurements);
            this.data.currencyIds = twist(this.data.currencyIds);
            this.data.counts = twist(this.data.counts);
            this.data.groupDomains = twist(this.data.groupDomains);

            // The sorted column's groupId is expressed in PRE-flip coordinates:
            // after the swap it denotes a row, so any later load/expand would
            // re-sort the rows against a stale or foreign column. Resetting is
            // the safe option (transposing is only valid for the Total column).
            this.metaData.sortedColumn = null;

            this.notify();
        });
    }
    /**
     * Returns a domain representation of a group.
     *
     * @param {Object} group
     * @returns {Array[]}
     */
    getGroupDomain(group) {
        const config = { metaData: this.metaData, data: this.data };
        return getGroupDomain(group, config);
    }
    /**
     * Returns a description of the pivot table.
     *
     * @returns {Object}
     */
    getTable() {
        const headers = getTableHeaders(this.data, this.metaData);
        return {
            headers,
            rows: getTableRows(
                this.data.rowGroupTree,
                headers.at(-1),
                this.data,
                this.metaData,
            ),
        };
    }
    /**
     * Returns the total number of columns of the pivot table, as exported to
     * XLSX: the row-title column, one column per leaf column group and per
     * active measure, and the "Total" column group (one column per active
     * measure) when there is more than one leaf.
     *
     * @returns {number}
     */
    getTableWidth() {
        const leafCounts = getLeafCounts(this.data.colGroupTree);
        const leafCount =
            leafCounts[JSON.stringify(this.data.colGroupTree.root.values)];
        return computeExportedTableWidth(
            leafCount,
            this.metaData.activeMeasures.length,
        );
    }
    /**
     * @returns {boolean} true iff there's no data in the table
     */
    hasData() {
        return hasData(this.data);
    }
    /**
     * @override
     * @param {SearchParams} searchParams
     */
    async load(searchParams) {
        this.searchParams = searchParams;
        // pivot_measures from the favorite/action context seeds the active
        // measures when the favorite is (de)activated — i.e. when its value
        // changes — but must NOT keep re-overriding a measure toggled through
        // the UI on every later reload while the same favorite stays active.
        // We therefore consume it only when the context value actually changes
        // (compared by value: the search model may rebuild the array each load).
        const rawPivotMeasures = searchParams.context.pivot_measures;
        const pivotMeasuresKey = JSON.stringify(rawPivotMeasures ?? null);
        let processedMeasures = null;
        if (pivotMeasuresKey !== this.lastPivotMeasuresKey) {
            this.lastPivotMeasuresKey = pivotMeasuresKey;
            processedMeasures = processMeasure(rawPivotMeasures);
        }
        const activeMeasures = processedMeasures || this.metaData.activeMeasures;
        const metaData = this._buildMetaData({ activeMeasures });
        if (!this.reload) {
            metaData.rowGroupBys =
                searchParams.context.pivot_row_groupby ||
                (searchParams.groupBy.length
                    ? searchParams.groupBy
                    : metaData.rowGroupBys);
            this.reload = true;
        } else {
            metaData.rowGroupBys = searchParams.groupBy.length
                ? searchParams.groupBy
                : searchParams.context.pivot_row_groupby || metaData.rowGroupBys;
        }
        metaData.colGroupBys =
            searchParams.context.pivot_column_groupby || this.metaData.colGroupBys;

        if (
            JSON.stringify(metaData.rowGroupBys) !==
            JSON.stringify(this.metaData.rowGroupBys)
        ) {
            metaData.expandedRowGroupBys = [];
        }
        if (
            JSON.stringify(metaData.colGroupBys) !==
            JSON.stringify(this.metaData.colGroupBys)
        ) {
            metaData.expandedColGroupBys = [];
        }

        const allActivesMeasures = new Set(this.metaData.activeMeasures);
        if (processedMeasures) {
            processedMeasures.forEach((e) => allActivesMeasures.add(e));
        }

        metaData.measures = computeReportMeasures(
            metaData.fields,
            metaData.fieldAttrs,
            [...allActivesMeasures],
        );
        // A stale favorite/context measure (removed or renamed field) has no
        // entry in `measures`; keep it in activeMeasures and the renderer's
        // `measures[measure].type` dereference crashes the whole view. Drop it
        // instead, falling back to __count so the pivot stays usable.
        metaData.activeMeasures = dropUnknownMeasures(
            metaData.activeMeasures,
            metaData.measures,
        );
        const config = { metaData, data: this.data };
        await addPropertyFieldDefs(
            this.orm,
            metaData.resModel,
            searchParams.context,
            metaData.fields,
            new Set([...metaData.rowGroupBys, ...metaData.colGroupBys]),
        );
        return this._loadData(config);
    }
    /**
     * Sort the rows, depending on the values of a given column.
     *
     * @param {Object} sortedColumn
     */
    sortRows(sortedColumn) {
        if (this.race.getCurrentProm()) {
            return; // we are currently reloading the table
        }

        const config = { metaData: this.metaData, data: this.data };
        this._sortRows(sortedColumn, config);

        this.notify();
    }
    /**
     * Toggle the active state for a given measure, then reload the data
     * if this turns out to be necessary.
     *
     * @param {string} fieldName
     * @returns {Promise}
     */
    async toggleMeasure(fieldName) {
        this.nextActiveMeasures = this.nextActiveMeasures || [
            ...this.metaData.activeMeasures,
        ];
        const activeMeasures = this.nextActiveMeasures;
        const index = activeMeasures.indexOf(fieldName);
        if (index !== -1) {
            activeMeasures.splice(index, 1);
            // Removing a measure needs no reload, but a load may be in
            // flight (or start while we wait): wait the table out, then
            // rebuild from the CURRENT metaData so the landed load's
            // groupBys/data stay paired. Assigning a pre-await snapshot
            // here used to revert metaData under the fresh data and crash
            // the renderer.
            while (this.race.getCurrentProm()) {
                await this.race.getCurrentProm();
            }
            const metaData = this._buildMetaData();
            metaData.activeMeasures = activeMeasures;
            this.metaData = metaData;
        } else {
            activeMeasures.push(fieldName);
            const metaData = this._buildMetaData();
            metaData.activeMeasures = activeMeasures;
            const config = { metaData, data: this.data };
            await this._loadData(config);
            this.useSampleModel = false;
        }
        this.nextActiveMeasures = null;
        this.notify();
    }

    //--------------------------------------------------------------------------
    // Protected
    //--------------------------------------------------------------------------

    /**
     * Return a copy of this.metaData, extended with optional params.
     *
     * @protected
     * @param {Object} params
     * @returns {Object}
     */
    _buildMetaData(params) {
        const metaData = { ...this.metaData, ...params };
        metaData.activeMeasures = [...metaData.activeMeasures];
        metaData.colGroupBys = [...metaData.colGroupBys];
        metaData.rowGroupBys = [...metaData.rowGroupBys];
        metaData.expandedColGroupBys = [...metaData.expandedColGroupBys];
        metaData.expandedRowGroupBys = [...metaData.expandedRowGroupBys];
        metaData.customGroupBys = new Map([...metaData.customGroupBys]);
        metaData.sortedColumn = metaData.sortedColumn
            ? { ...metaData.sortedColumn }
            : null;
        metaData.domain = this.searchParams.domain;
        Object.defineProperty(metaData, "fullColGroupBys", {
            get() {
                return [...metaData.colGroupBys, ...metaData.expandedColGroupBys];
            },
        });
        Object.defineProperty(metaData, "fullRowGroupBys", {
            get() {
                return [...metaData.rowGroupBys, ...metaData.expandedRowGroupBys];
            },
        });
        return metaData;
    }
    /**
     * Expand a group by using groupBy to split it.
     *
     * @protected
     * @param {Array[]} groupId
     * @param {'row'|'col'} type
     * @param {Config} config
     * @returns {Promise<boolean>} false when the expansion was superseded by
     *   a newer request and its result discarded
     */
    async _expandGroup(groupId, type, config) {
        const { metaData } = config;
        const group = {
            rowValues: groupId[0],
            colValues: groupId[1],
            type: type,
        };
        const groupValues = type === "row" ? groupId[0] : groupId[1];
        const groupBys =
            type === "row" ? metaData.fullRowGroupBys : metaData.fullColGroupBys;
        if (groupValues.length >= groupBys.length) {
            throw new Error("Cannot expand group");
        }
        const groupBy = groupBys[groupValues.length];
        let leftDivisors;
        let rightDivisors;
        if (group.type === "row") {
            leftDivisors = [[groupBy]];
            rightDivisors = sections(metaData.fullColGroupBys);
        } else {
            leftDivisors = sections(metaData.fullRowGroupBys);
            rightDivisors = [[groupBy]];
        }
        const divisors = cartesian(leftDivisors, rightDivisors);
        delete group.type;
        return this._subdivideGroup(group, divisors, config);
    }

    /**
     * Register ``promise`` on the shared ``this.keepLast``, but always
     * settle: ``KeepLast.add``'s wrapper never resolves once superseded,
     * which would leave a mutexed caller (expandGroup/addGroupBy) pending
     * forever and wedge every queued mutation behind it. Instead, resolve
     * with the SUPERSEDED sentinel as soon as a newer request is registered,
     * so callers can discard their stale result and release the mutex.
     *
     * @protected
     * @param {Promise<any>} promise
     * @returns {Promise<any>} the promise result, or SUPERSEDED
     */
    _keepLastAdd(promise) {
        for (const notifySuperseded of this._supersessionWatchers) {
            notifySuperseded(SUPERSEDED);
        }
        this._supersessionWatchers.length = 0;
        const supersededProm = new Promise((resolve) => {
            this._supersessionWatchers.push(resolve);
        });
        return Promise.race([this.keepLast.add(promise), supersededProm]);
    }

    async _getGroupsSubdivision(params, groupInfo) {
        const { resModel, groupDomain, groupingSets, measureSpecs, kwargs } = params;
        const result = await this.orm.formattedReadGroupingSets(
            resModel,
            groupDomain,
            groupingSets,
            measureSpecs,
            kwargs,
        );
        return groupInfo.map((info) => ({
            ...info,
            subGroups: result[info.subGroupIndex],
        }));
    }

    /**
     * Initialize/Reinitialize data and subdivide the group 'Total'.
     *
     * @protected
     * @param {Config} config
     * @param {boolean} prune
     */
    async _loadData(config, prune = true) {
        config.data = /** @type {any} */ ({});
        const { data, metaData } = config;
        data.rowGroupTree = {
            root: { labels: [], values: [] },
            directSubTrees: new Map(),
        };
        data.colGroupTree = {
            root: { labels: [], values: [] },
            directSubTrees: new Map(),
        };
        data.measurements = {};
        data.currencyIds = {};
        data.counts = {};
        data.groupDomains = {};
        data.numbering = {};
        const key = JSON.stringify([[], []]);
        data.groupDomains[key] = metaData.domain;

        const group = { rowValues: [], colValues: [] };
        const leftDivisors = sections(metaData.fullRowGroupBys);
        const rightDivisors = sections(metaData.fullColGroupBys);
        const divisors = cartesian(leftDivisors, rightDivisors);

        if (!(await this._subdivideGroup(group, divisors, config))) {
            // Superseded by a newer load: leave the state to it and never
            // settle (KeepLast semantics). The shared race must stay pending
            // until the superseding load finishes, so the race-guards on
            // mutations keep dropping clicks meanwhile; callers only ever
            // await the race promise, which the newer load resolves.
            return new Promise(() => {});
        }

        // keep folded groups folded after the reload if the structure of the table is the same
        if (prune && hasData(data) && hasData(this.data)) {
            if (
                symmetricalDifference(metaData.rowGroupBys, this.metaData.rowGroupBys)
                    .length === 0
            ) {
                pruneTree(data.rowGroupTree, this.data.rowGroupTree);
            }
            if (
                symmetricalDifference(metaData.colGroupBys, this.metaData.colGroupBys)
                    .length === 0
            ) {
                pruneTree(data.colGroupTree, this.data.colGroupTree);
            }
        }

        this.data = config.data;
        this.metaData = config.metaData;
    }
    /**
     * Extract the information in the read_group results and develop
     * rowGroupTree, colGroupTree, measurements, counts, and groupDomains.
     *
     * @protected
     * @param {Object} group
     * @param {Object[]} groupSubdivisions
     * @param {Config} config
     */
    _prepareData(group, groupSubdivisions, config) {
        return aggregateSubdivisions(group, groupSubdivisions, config, {
            sortRows: (sortedColumn, cfg) => this._sortRows(sortedColumn, cfg),
        });
    }
    /**
     * Get all partitions of a given group and enrich data structures.
     *
     * @protected
     * @param {Object} group
     * @param {Array[]} divisors
     * @param {Config} config
     * @returns {Promise<boolean>} false when the fetch was superseded by a
     *   newer request and its result discarded
     */
    async _subdivideGroup(group, divisors, config) {
        const { data } = config;
        const key = JSON.stringify([group.rowValues, group.colValues]);

        // A group KNOWN to be empty (count 0) needs no fetch; an unknown
        // count (key absent) must fetch. (`!counts[key] || counts[key] > 0`
        // was a tautology — count 0 still fetched.)
        if (!(key in data.counts) || data.counts[key] > 0) {
            const subGroup = {
                rowValues: group.rowValues,
                colValues: group.colValues,
            };
            const groupDomainValue = getGroupDomain(subGroup, config);
            const measureSpecsList = getMeasureSpecs(config);
            if (!measureSpecsList.includes("__count")) {
                measureSpecsList.push("__count");
            }
            const resModel = config.metaData.resModel;
            const kwargs = { context: this.searchParams.context };
            const groupingSets = [];
            const groupInfo = [];
            divisors.forEach((divisor) => {
                const groupBy = getGroupBySpecs(
                    divisor[0],
                    divisor[1],
                    config.metaData.fields,
                );
                const sortedKey = JSON.stringify(groupBy.toSorted());
                let index = groupingSets.findIndex(
                    (value) => JSON.stringify(value.toSorted()) === sortedKey,
                );
                if (index === -1) {
                    index = groupingSets.length;
                    groupingSets.push(groupBy);
                }
                groupInfo.push({
                    group: subGroup,
                    rowGroupBy: divisor[0],
                    colGroupBy: divisor[1],
                    subGroupIndex: index,
                });
            });

            const params = {
                resModel,
                groupDomain: groupDomainValue,
                measureSpecs: measureSpecsList,
                kwargs,
                groupingSets,
            };
            const groupSubdivisions = await this._keepLastAdd(
                this._getGroupsSubdivision(params, groupInfo),
            );
            if (groupSubdivisions === SUPERSEDED) {
                return false;
            }
            if (groupSubdivisions.length) {
                this._prepareData(group, groupSubdivisions, config);
            }
        }
        return true;
    }
    /**
     * Sort the rows, depending on the values of a given column.
     *
     * @protected
     * @param {Object} sortedColumn
     * @param {Config} config
     */
    _sortRows(sortedColumn, config) {
        const metaData = config.metaData || this.metaData;
        const data = config.data || this.data;
        const colGroupValues = sortedColumn.groupId[1];
        const colKey = JSON.stringify(colGroupValues);
        metaData.sortedColumn = sortedColumn;

        const sortFunction = (tree) => (subTreeKey) => {
            const subTree = tree.directSubTrees.get(subTreeKey);
            const cellKey = makeCellKey(JSON.stringify(subTree.root.values), colKey);
            const value = getCellValue(cellKey, sortedColumn.measure, data) || 0;
            return sortedColumn.order === "asc" ? value : -value;
        };

        sortTree(sortFunction, data.rowGroupTree);
    }
}
