// @ts-check
/** @odoo-module native */

/** @module @web/views/graph/graph_model */

import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { sortBy } from "@web/core/utils/collections/arrays";
import { InFlight, KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { addPropertyFieldDefs, Model } from "@web/model/model";
import { rankInterval } from "@web/search/utils/dates";
import { getGroupBy } from "@web/search/utils/group_by";
import { GROUPABLE_TYPES } from "@web/search/utils/misc";
import { user } from "@web/services/user";
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
        const fieldName = groupBy[0]?.fieldName;
        const sequentialField =
            cumulatedStart && SEQUENTIAL_TYPES.includes(fields[fieldName]?.type)
                ? fieldName
                : null;
        const sequentialSpec = sequentialField && groupBy[0].spec;
        const measures = ["__count"];
        let fieldAggregate = "__count",
            monetaryAggregates;
        if (measure !== "__count") {
            const { currency_field, name, type } = fields[measure];
            let { aggregator } = fields[measure];
            if (type === "many2one") {
                aggregator = "count_distinct";
            }
            if (aggregator === undefined) {
                throw new Error(
                    `No aggregate function has been provided for the measure '${measure}'`,
                );
            }
            if (type === "monetary" && currency_field) {
                monetaryAggregates = [
                    `${currency_field}:array_agg_distinct`,
                    `${name}:sum_currency`,
                ];
                measures.push(...monetaryAggregates);
            }
            fieldAggregate = `${measure}:${aggregator}`;
            measures.push(fieldAggregate);
        }

        const numbering = {};

        const groups = await this.orm.formattedReadGroup(
            resModel,
            domain,
            groupBy.map((gb) => gb.spec),
            measures,
            {
                context: { fill_temporal: true, ...this.searchParams.context },
            },
        );
        /** @type {any} */
        let startGroups = false;
        const firstDatedGroup =
            sequentialField && groups.find((group) => group[sequentialSpec]);
        if (
            cumulatedStart &&
            firstDatedGroup &&
            domain.some((leaf) => leaf.length === 3 && leaf[0] === sequentialField)
        ) {
            const firstDate = firstDatedGroup[sequentialSpec][0];
            const newDomain = Domain.combine(
                [
                    new Domain([[sequentialField, "<", firstDate]]),
                    Domain.removeDomainLeaves(domain, [sequentialField]),
                ],
                "AND",
            ).toList();
            startGroups = await this.orm.formattedReadGroup(
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
        const graphCurrencies = new Set();
        const defaultCurrency = user.activeCompany?.currency_id;
        const dataPoints = [];
        const cumulatedStartValue = {};
        const cumulatedStartConverted = {};
        if (startGroups) {
            for (const group of /** @type {any[]} */ (startGroups)) {
                const rawValues = [];
                for (const gb of groupBy.filter(
                    (gb) => gb.fieldName !== sequentialField,
                )) {
                    rawValues.push({ [gb.spec]: group[gb.spec] });
                }
                const key = JSON.stringify(rawValues);
                let value = group[fieldAggregate];
                if (monetaryAggregates) {
                    const currencies = (group[monetaryAggregates[0]] || []).filter(
                        (currencyId) => currencyId != null,
                    );
                    cumulatedStartConverted[key] = group[monetaryAggregates[1]];
                    if (currencies.length > 1) {
                        value = cumulatedStartConverted[key];
                        graphCurrencies.add(defaultCurrency);
                    } else if (currencies.length === 1) {
                        graphCurrencies.add(currencies[0]);
                    }
                }
                cumulatedStartValue[key] = value;
            }
        }
        for (const group of groups) {
            const { __domain, __count } = group;
            const labels = [];
            const rawValues = [];
            let isFalsyXGroup = false;
            for (const [gbIndex, gb] of groupBy.entries()) {
                let label;
                const val = group[gb.spec];
                rawValues.push({ [gb.spec]: val });
                const fieldName = gb.fieldName;
                const { type } = fields[fieldName];
                if (type === "boolean") {
                    label = `${val}`;
                } else if (type === "integer") {
                    label = val === false ? "0" : `${val}`;
                } else if (val === false) {
                    label = this._getDefaultFilterLabel(gb);
                    if (gbIndex === 0) {
                        isFalsyXGroup = true;
                    }
                } else if (["many2many", "many2one"].includes(type)) {
                    const [id, name] = val;
                    const key = JSON.stringify([fieldName, name]);
                    if (!numbering[key]) {
                        numbering[key] = {};
                    }
                    const numbers = numbering[key];
                    if (!numbers[id]) {
                        numbers[id] = Object.keys(numbers).length + 1;
                    }
                    const num = numbers[id];
                    label = num === 1 ? name : `${name} (${num})`;
                } else if (type === "selection") {
                    const selected = fields[fieldName].selection.find(
                        (s) => s[0] === val,
                    );
                    label = selected ? selected[1] : String(val);
                } else if (["date", "datetime"].includes(type)) {
                    label = val[1];
                } else {
                    label = val;
                }
                labels.push(label);
            }

            const value = group[fieldAggregate] === false ? 0 : group[fieldAggregate];
            if (!Number.isInteger(value)) {
                metaData.allIntegers = false;
            }
            const groupId = JSON.stringify(rawValues.slice(1));
            const dataPoint = {
                count: __count,
                domain: __domain,
                value,
                labels,
                isFalsyXGroup,
                identifier: JSON.stringify(rawValues),
                xIdentifier: JSON.stringify(rawValues.slice(0, 1)),
                datasetId: groupId,
                cumulatedStart: cumulatedStartValue[groupId] || 0,
                convertedCumulatedStart: cumulatedStartConverted[groupId] || 0,
            };
            if (monetaryAggregates) {
                const currencies = (group[monetaryAggregates[0]] || []).filter(
                    (currencyId) => currencyId != null,
                );
                dataPoint.currencyId = currencies[0];
                dataPoint.convertedValue = group[monetaryAggregates[1]];
                if (currencies.length > 1) {
                    dataPoint.currencyId = defaultCurrency;
                    dataPoint.value = dataPoint.convertedValue;
                }
                if (currencies.length && __count !== 0) {
                    graphCurrencies.add(dataPoint.currencyId);
                }
            }
            dataPoints.push(dataPoint);
        }
        for (const dataPoint of dataPoints) {
            if (graphCurrencies.size > 1) {
                dataPoint.currencyId = defaultCurrency;
                if (monetaryAggregates) {
                    dataPoint.value = dataPoint.convertedValue;
                    dataPoint.cumulatedStart = dataPoint.convertedCumulatedStart;
                }
            }
            delete dataPoint.convertedValue;
            delete dataPoint.convertedCumulatedStart;
        }
        return dataPoints;
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
