// @ts-check
/** @odoo-module native */

/** @module @web/views/graph/graph_model */

import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { sortBy } from "@web/core/utils/collections/arrays";
import { InFlight, KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { addPropertyFieldDefs, Model } from "@web/model/model";
import { rankInterval } from "@web/search/utils/dates";
import { getGroupBy } from "@web/search/utils/group_by";
import { GROUPABLE_TYPES } from "@web/search/utils/misc";
import {
    applyCurrencyFallback,
    foldCumulatedStart,
    getGroupLabels,
    getMeasureSpec,
    getRawValue,
    makeDataPoint,
} from "@web/views/graph/graph_data_points";
import { computeReportMeasures, processMeasure } from "@web/views/view_measurements";

export const SEP = " / ";
export const DATA_LIMIT = 80;

const SEQUENTIAL_TYPES = ["date", "datetime"];

/**
 * @typedef {import("@web/model/types").SearchParams} SearchParams
 */

export class GraphModel extends Model {
    static reactiveRenderers = true;

    /**
     * @override
     */
    setup(params) {
        this.keepLast = new KeepLast({ rejectSuperseded: true });
        this.fetches = new InFlight();
        /** @type {any} */
        const _fetchDataPoints = this._fetchDataPoints.bind(this);
        this._fetchDataPoints = (...args) =>
            this.fetches.track(_fetchDataPoints(...args));

        this.initialGroupBy = null;
        this.contextParamsSeen = {};

        this.metaData = params;
        this.data = null;
        this.searchParams = null;
        this.lineOverlayDataset = null;
        this.forceAllDataPoints = false;
    }

    /**
     * @param {SearchParams} searchParams
     */
    async load(searchParams) {
        const previousSearchParams = this.searchParams;
        this.searchParams = searchParams;
        if (
            this.forceAllDataPoints &&
            previousSearchParams &&
            (JSON.stringify(previousSearchParams.domain) !==
                JSON.stringify(searchParams.domain) ||
                JSON.stringify(previousSearchParams.groupBy) !==
                    JSON.stringify(searchParams.groupBy))
        ) {
            this.forceAllDataPoints = false;
        }
        if (!this.initialGroupBy) {
            this.initialGroupBy =
                searchParams.context.graph_groupbys || this.metaData.groupBy;
        }
        this._consumeContextParams(searchParams.context);
        const metaData = this._buildMetaData();
        await addPropertyFieldDefs(
            this.orm,
            metaData.resModel,
            searchParams.context,
            metaData.fields,
            metaData.groupBy.map((gb) => gb.fieldName),
        );
        await this._fetchDataPoints(metaData);
    }

    async forceLoadAll() {
        while (this.fetches.isBusy) {
            await this.fetches.whenIdle();
        }
        this.forceAllDataPoints = true;
        this._prepareData();
        this.notify();
    }

    /**
     * @override
     */
    hasData() {
        return /** @type {any} */ (this).dataPoints?.length > 0;
    }

    /**
     * @param {Object} params
     */
    async updateMetaData(params) {
        if ("measure" in params) {
            const metaData = this._buildMetaData(params);
            if (!(await this._fetchDataPoints(metaData))) {
                return;
            }
            this.useSampleModel = false;
        } else {
            while (this.fetches.isBusy) {
                await this.fetches.whenIdle();
            }
            this.metaData = { ...this.metaData, ...params };
            this._prepareData();
        }
        this.notify();
    }

    /**
     * @protected
     * @param {Object} context
     */
    _consumeContextParams(context) {
        const metaData = this.metaData;
        const seen = this.contextParamsSeen;
        const changed = (key) => {
            if (context[key] === seen[key]) {
                return false;
            }
            seen[key] = context[key];
            return true;
        };
        const measureChanged = changed("graph_measure");
        const modeChanged = changed("graph_mode");
        const orderChanged = changed("graph_order");
        const stackedChanged = changed("graph_stacked");
        const cumulatedChanged = changed("graph_cumulated");
        if (measureChanged && context.graph_measure) {
            metaData.measure = context.graph_measure;
        }
        if (modeChanged && context.graph_mode) {
            metaData.mode = context.graph_mode;
        }
        if (metaData.mode !== "pie" && metaData.mode !== "scatter") {
            if (orderChanged && "graph_order" in context) {
                metaData.order = context.graph_order;
            }
            if (stackedChanged && "graph_stacked" in context) {
                metaData.stacked = context.graph_stacked;
            }
            if (
                metaData.mode === "line" &&
                cumulatedChanged &&
                "graph_cumulated" in context
            ) {
                metaData.cumulated = context.graph_cumulated;
            }
        }
    }

    /**
     * @protected
     * @param {Object} [params={}]
     * @returns {Object}
     */
    _buildMetaData(params) {
        const { domain, context, groupBy } = this.searchParams;

        const metaData = { ...this.metaData, context };
        metaData.domain = domain;
        metaData.groupBy = groupBy.length ? groupBy : this.initialGroupBy;

        this._normalize(metaData);

        metaData.measures = computeReportMeasures(
            metaData.fields,
            metaData.fieldAttrs,
            [...(metaData.viewMeasures || []), metaData.measure],
        );
        if (metaData.measure !== "__count" && !metaData.measures[metaData.measure]) {
            console.warn(
                `Measure "${metaData.measure}" has no field definition (removed or renamed field?); falling back to Count.`,
            );
            metaData.measure = "__count";
        }

        return Object.assign(metaData, params);
    }

    /**
     * @protected
     * @param {Object} metaData
     * @returns {Promise<boolean>}
     */
    async _fetchDataPoints(metaData) {
        let dataPoints;
        try {
            dataPoints = await this.keepLast.add(this._loadDataPoints(metaData));
        } catch (error) {
            if (error instanceof SupersededError) {
                return false;
            }
            throw error;
        }
        /** @type {any} */ (this).dataPoints = dataPoints;
        this.metaData = metaData;
        this._prepareData();
        return true;
    }

    /**
     * @protected
     * @param {Object[]} dataPoints
     * @param {boolean} forceUseAllDataPoints
     * @returns {Object}
     */
    _getData(dataPoints, forceUseAllDataPoints) {
        const { mode } = this.metaData;

        const dataPtMapping = new WeakMap();
        const datasetsTmp = {};
        let exceeds = false;

        const labels = [];
        const labelMap = {};
        for (const dataPt of dataPoints) {
            const datasetLabel = this._getDatasetLabel(dataPt);
            const datasetKey =
                mode === "pie" ? datasetLabel : (dataPt.datasetId ?? datasetLabel);
            const isNewDataset = !(datasetKey in datasetsTmp);

            const x = dataPt.labels.slice(0, mode === "pie" ? undefined : 1);
            const trueLabel = x.length ? x.join(SEP) : _t("Total");
            const key =
                mode === "pie"
                    ? (dataPt.identifier ?? JSON.stringify(x))
                    : (dataPt.xIdentifier ?? JSON.stringify(x));
            const isNewLabel = labelMap[key] === undefined;

            if (
                !forceUseAllDataPoints &&
                ((isNewDataset && Object.keys(datasetsTmp).length >= DATA_LIMIT) ||
                    (isNewLabel && labels.length >= DATA_LIMIT))
            ) {
                exceeds = true;
                continue;
            }
            if (isNewDataset) {
                datasetsTmp[datasetKey] = { label: datasetLabel };
            }
            dataPtMapping.set(dataPt, datasetsTmp[datasetKey]);

            if (isNewLabel) {
                labelMap[key] = labels.length;
                const label = x.length ? x.join(SEP) : _t("Total");
                labels.push(label);
            }
            dataPt.labelIndex = labelMap[key];
            dataPt.trueLabel = trueLabel;
        }

        for (const dataPt of dataPoints) {
            if (!dataPtMapping.has(dataPt)) {
                continue;
            }

            const {
                domain,
                labelIndex,
                trueLabel,
                value,
                identifier,
                cumulatedStart,
                currencyId,
            } = dataPt;
            const dataset = dataPtMapping.get(dataPt);
            if (!dataset.data) {
                const dataLength = labels.length;
                Object.assign(dataset, {
                    data: new Array(dataLength).fill(0),
                    cumulatedStart,
                    trueLabels: labels.slice(0, dataLength),
                    domains: Array.from({ length: dataLength }, () => []),
                    identifiers: new Set(),
                    currencyIds: new Array(dataLength).fill(),
                });
            }
            dataset.data[labelIndex] = value;
            dataset.domains[labelIndex] = domain;
            dataset.trueLabels[labelIndex] = trueLabel;
            dataset.identifiers.add(identifier);
            dataset.currencyIds[labelIndex] = currencyId;
        }

        const datasets = Object.values(datasetsTmp);

        return { datasets, labels, exceeds };
    }

    _getLineOverlayDataset() {
        const { stacked } = this.metaData;
        const datasets = this.data.datasets;
        let lineOverlayDataset = null;
        if (stacked && datasets.length > 1) {
            const label = _t("Sum");
            const data = [];
            const currencyIds = [];
            for (const dataset of datasets) {
                for (let i = 0; i < dataset.data.length; i++) {
                    data[i] = (data[i] || 0) + dataset.data[i];
                    currencyIds[i] = dataset.currencyIds[i] || currencyIds[i];
                }
            }
            lineOverlayDataset = {
                label,
                data,
                currencyIds,
                trueLabels: datasets[0].trueLabels,
            };
        }
        return lineOverlayDataset;
    }

    /**
     * @protected
     * @param {Object} dataPoint
     * @returns {string}
     */
    _getDatasetLabel(dataPoint) {
        const { measure, measures, mode } = this.metaData;
        const { labels } = dataPoint;
        if (mode === "pie") {
            return "";
        }
        return labels.slice(1).join(SEP) || measures[measure].string;
    }

    /**
     * @protected
     * @returns {string}
     */
    _getDefaultFilterLabel(gb) {
        return this.metaData.fields[gb?.fieldName]?.falsy_value_label || _t("None");
    }

    /**
     * @protected
     * @returns {Object[]}
     */
    _getProcessedDataPoints() {
        const { groupBy, mode, order, cumulated } = this.metaData;
        let processedDataPoints;
        /** @type {any[]} */
        const dataPoints = /** @type {any} */ (this).dataPoints;
        if (mode === "line" || mode === "scatter") {
            processedDataPoints = dataPoints.filter(
                (dataPoint) => !dataPoint.isFalsyXGroup,
            );
        } else if (mode === "pie") {
            processedDataPoints = dataPoints.filter(
                (dataPoint) => dataPoint.value > 0 && dataPoint.count !== 0,
            );
        } else {
            processedDataPoints = dataPoints.filter(
                (dataPoint) => dataPoint.count !== 0,
            );
        }

        if (order !== null && mode !== "pie" && groupBy.length && !cumulated) {
            const groupedDataPoints = Object.groupBy(
                processedDataPoints,
                (dataPt) => dataPt.xIdentifier ?? dataPt.labels[0],
            );
            const groups = Object.values(groupedDataPoints);
            const groupTotal = (group) =>
                group.reduce((sum, dataPt) => sum + dataPt.value, 0);
            processedDataPoints = sortBy(
                groups,
                groupTotal,
                order.toLowerCase(),
            ).flat();
        }

        return processedDataPoints;
    }

    /**
     * @protected
     * @param {Object} metaData
     * @returns {Promise<any[]>}
     */
    async _loadDataPoints(metaData) {
        metaData.allIntegers = true;
        const { measure, domain, fields, groupBy, resModel, cumulatedStart } = metaData;
        const xFieldName = groupBy[0]?.fieldName;
        const sequentialField =
            cumulatedStart && SEQUENTIAL_TYPES.includes(fields[xFieldName]?.type)
                ? xFieldName
                : null;
        const { measures, fieldAggregate, monetaryAggregates } = getMeasureSpec(
            measure,
            fields,
        );

        const groups = await this.orm.formattedReadGroup(
            resModel,
            domain,
            groupBy.map((gb) => gb.spec),
            measures,
            {
                context: { fill_temporal: true, ...this.searchParams.context },
            },
        );

        const graphCurrencies = new Set();
        const defaultCurrency = user.activeCompany?.currency_id;
        const startGroups = await this._fetchStartGroups(
            metaData,
            sequentialField,
            measures,
            groups,
        );
        const { cumulatedStartValue, cumulatedStartConverted } = startGroups
            ? foldCumulatedStart(startGroups, {
                  groupBy,
                  sequentialField,
                  fieldAggregate,
                  monetaryAggregates,
                  defaultCurrency,
                  graphCurrencies,
              })
            : { cumulatedStartValue: {}, cumulatedStartConverted: {} };

        /** @type {import("./graph_data_points").Numbering} */
        const numbering = {};
        const getDefaultFilterLabel = (gb) => this._getDefaultFilterLabel(gb);
        const dataPoints = [];
        for (const group of groups) {
            // Read before makeDataPoint, which may swap in a converted value.
            if (!Number.isInteger(getRawValue(group, fieldAggregate))) {
                metaData.allIntegers = false;
            }
            const { labels, rawValues, isFalsyXGroup } = getGroupLabels(group, {
                groupBy,
                fields,
                numbering,
                getDefaultFilterLabel,
            });
            dataPoints.push(
                makeDataPoint(group, {
                    labels,
                    rawValues,
                    isFalsyXGroup,
                    fieldAggregate,
                    monetaryAggregates,
                    defaultCurrency,
                    graphCurrencies,
                    cumulatedStartValue,
                    cumulatedStartConverted,
                }),
            );
        }
        return applyCurrencyFallback(dataPoints, {
            graphCurrencies,
            defaultCurrency,
            hasMonetaryAggregates: Boolean(monetaryAggregates),
        });
    }

    /**
     * The pre-window groups a cumulated graph starts from, or `false` when there
     * is nothing to accumulate from: no cumulated start, no sequential x field,
     * no dated group, or a domain that does not bound the sequential field.
     *
     * @protected
     * @param {Object} metaData
     * @param {string | null} sequentialField
     * @param {string[]} measures
     * @param {Object[]} groups
     * @returns {Promise<any>}
     */
    async _fetchStartGroups(metaData, sequentialField, measures, groups) {
        const { domain, groupBy, resModel, cumulatedStart } = metaData;
        if (!cumulatedStart || !sequentialField) {
            return false;
        }
        const sequentialSpec = groupBy[0].spec;
        const firstDatedGroup = groups.find((group) => group[sequentialSpec]);
        if (
            !firstDatedGroup ||
            !domain.some((leaf) => leaf.length === 3 && leaf[0] === sequentialField)
        ) {
            return false;
        }
        const firstDate = firstDatedGroup[sequentialSpec][0];
        const newDomain = Domain.combine(
            [
                new Domain([[sequentialField, "<", firstDate]]),
                Domain.removeDomainLeaves(domain, [sequentialField]),
            ],
            "AND",
        ).toList();
        return this.orm.formattedReadGroup(
            resModel,
            newDomain,
            groupBy
                .filter((gb) => gb.fieldName !== sequentialField)
                .map((gb) => gb.spec),
            measures,
            {
                context: { ...this.searchParams.context },
            },
        );
    }

    /**
     * @protected
     * @param {Object} metaData
     */
    _normalize(metaData) {
        const { fields } = metaData;
        const groupBy = [];
        for (const gb of metaData.groupBy) {
            let ngb = gb;
            if (typeof gb === "string") {
                ngb = getGroupBy(gb, fields);
            }
            groupBy.push(ngb);
        }

        const processedGroupBy = [];
        for (const gb of groupBy) {
            const { fieldName, interval } = gb;
            if (!fieldName.includes(".")) {
                const { groupable, type } = fields[fieldName];
                if (
                    !groupable ||
                    ["id", "__count"].includes(fieldName) ||
                    !GROUPABLE_TYPES.includes(type)
                ) {
                    continue;
                }
            }
            const index = processedGroupBy.findIndex(
                (gb) => gb.fieldName === fieldName,
            );
            if (index === -1) {
                processedGroupBy.push(gb);
            } else if (interval) {
                const registeredInterval = processedGroupBy[index].interval;
                if (rankInterval(registeredInterval) < rankInterval(interval)) {
                    processedGroupBy.splice(index, 1, gb);
                }
            }
        }
        metaData.groupBy = processedGroupBy;

        metaData.measure = processMeasure(metaData.measure);
    }

    /**
     * @protected
     */
    _prepareData() {
        const processedDataPoints = this._getProcessedDataPoints();
        this.data = this._getData(processedDataPoints, this.forceAllDataPoints);
        this.lineOverlayDataset = null;
        if (this.metaData.mode === "bar") {
            this.lineOverlayDataset = this._getLineOverlayDataset();
        }
    }
}
