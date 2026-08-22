// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { colorScheme } from "@web/core/color_scheme";
import {
    darkenColor,
    DEFAULT_BG,
    getBorderWhite,
    getColor,
    getCustomColor,
    lightenColor,
} from "@web/core/colors/colors";
import { getFieldCodec } from "@web/core/field_codec";
import { formatFieldFloat, formatMonetary } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { sortBy } from "@web/core/utils/collections/arrays";

import { SEP } from "./graph_model.js";

const NO_DATA = _t("No data");

const graphLegendColor = () => getCustomColor("#111827", "#ffffff");
const graphGridColor = () => getCustomColor("rgba(0,0,0,.1)", "rgba(255,255,255,.15)");
const graphLabelColor = () => getCustomColor("#111827", "#E4E4E4");
const noDataColor = () => getCustomColor(DEFAULT_BG, "#3C3E4B");

export const gridOnTop = {
    id: "gridOnTop",
    afterDraw: (chart) => {
        const elements = chart.getDatasetMeta(0).data || [];
        const ctx = chart.ctx;
        const chartArea = chart.chartArea;
        const yAxis = chart.scales.y;
        const xAxis = chart.scales.x;

        ctx.lineWidth = 1;
        ctx.strokeStyle = graphGridColor();

        yAxis.ticks.forEach((value, index) => {
            const y = yAxis.getPixelForTick(index);
            ctx.beginPath();
            ctx.moveTo(chartArea.left, y);
            ctx.lineTo(chartArea.right, y);
            ctx.moveTo(chartArea.left - 8, y);
            ctx.lineTo(chartArea.left, y);
            ctx.setLineDash([]);
            ctx.stroke();
        });

        xAxis.ticks.forEach((value, tickIndex) => {
            const x = xAxis.getPixelForTick(tickIndex);
            ctx.beginPath();
            ctx.moveTo(x, chartArea.bottom);
            ctx.lineTo(x, chartArea.bottom + 8);
            ctx.stroke();
        });

        elements.forEach((point, eltIndex) => {
            xAxis.ticks.forEach((value, tickIndex) => {
                if (point.active && eltIndex === tickIndex) {
                    const x = xAxis.getPixelForTick(tickIndex);
                    ctx.beginPath();
                    ctx.moveTo(x, chartArea.top);
                    ctx.lineTo(x, chartArea.bottom);
                    ctx.strokeStyle = graphGridColor();
                    ctx.stroke();
                }
            });
        });
    },
};

/**
 * @param {Object} chartArea
 * @returns {string}
 */
export function getMaxWidth(chartArea) {
    const { left, right } = chartArea;
    return `${Math.floor((right - left) / 1.618)}px`;
}

/**
 * @param {string} label
 * @returns {string}
 */
function shortenLabel(label) {
    const groups = label.toString().split(SEP);
    let shortLabel = groups.slice(0, 3).join(SEP);
    if (shortLabel.length > 30) {
        shortLabel = `${shortLabel.slice(0, 30)}...`;
    } else if (groups.length > 3) {
        shortLabel = `${shortLabel}${SEP}...`;
    }
    return shortLabel;
}

/**
 * @param {number} value
 * @param {boolean} [allIntegers=true]
 * @param {string} [formatType=""]
 * @returns {string}
 */
function formatValue(value, allIntegers = true, formatType = "") {
    const largeNumber = Math.abs(value) >= 1000;
    if (formatType) {
        return getFieldCodec(formatType).format(value);
    }
    if (allIntegers && !largeNumber) {
        return String(value);
    }
    if (largeNumber) {
        return formatFieldFloat(value, {
            humanReadable: true,
            decimals: 2,
            minIntegerDigits: 1,
        });
    }
    return formatFieldFloat(value);
}

/**
 * @param {Object} data
 * @param {Object} metaData
 * @param {Object} [lineOverlayDataset]
 * @returns {Object}
 */
export function styleBarChartData(data, metaData, lineOverlayDataset) {
    const { stacked } = metaData;
    for (let index = 0; index < data.datasets.length; ++index) {
        const dataset = data.datasets[index];
        const itemColor = getColor(index, data.datasets.length);
        if (stacked) {
            dataset.stack = "";
        }
        dataset.backgroundColor = itemColor;
        dataset.borderRadius = 4;
    }
    if (lineOverlayDataset) {
        Object.assign(lineOverlayDataset, {
            type: "line",
            order: -1,
            tension: 0,
            fill: false,
            pointHitRadius: 20,
            pointRadius: 5,
            pointHoverRadius: 10,
            backgroundColor: getCustomColor("#343a40", "#e9ecef"),
            borderColor: getCustomColor("rgba(0,0,0,.3)", "rgba(255,255,255,.5)"),
            borderWidth: 2,
            lineWidth: 3,
        });
        return {
            ...data,
            datasets: [...data.datasets, lineOverlayDataset],
        };
    }

    return data;
}

/**
 * @param {Object} data
 * @param {Object} metaData
 * @returns {Object}
 */
export function styleLineChartData(data, metaData) {
    const { cumulated } = metaData;
    for (let index = 0; index < data.datasets.length; ++index) {
        const dataset = data.datasets[index];
        const itemColor = getColor(index, data.datasets.length);
        dataset.backgroundColor = getCustomColor(
            lightenColor(itemColor, 0.5),
            darkenColor(itemColor, 0.5),
        );
        dataset.cubicInterpolationMode = "monotone";
        dataset.borderColor = itemColor;
        dataset.borderWidth = 2;
        dataset.hoverBackgroundColor = dataset.borderColor;
        dataset.pointRadius = 3;
        dataset.pointHoverRadius = 6;
        if (cumulated && !dataset._fcCumulated) {
            let accumulator = dataset.cumulatedStart;
            dataset.data = dataset.data.map((value) => {
                accumulator += value;
                return accumulator;
            });
            dataset._fcCumulated = true;
        }
        if (data.labels.length === 1) {
            dataset.data.unshift(undefined);
            dataset.trueLabels.unshift(undefined);
            dataset.domains.unshift(undefined);
            dataset.currencyIds?.unshift(undefined);
        }
        dataset.pointBackgroundColor = dataset.borderColor;
    }
    data.labels = data.labels.length > 1 ? data.labels : ["", ...data.labels, ""];
    return data;
}

/**
 * @param {Object} data
 * @returns {Object}
 */
export function stylePieChartData(data) {
    const hasNoDataPlaceholder =
        data.labels.length > 0 &&
        data.labels[data.labels.length - 1] === NO_DATA &&
        data.datasets.length === 1;
    if (hasNoDataPlaceholder) {
        return data;
    }
    const colors = data.labels.map((_, index) => getColor(index, data.labels.length));
    const borderColor = getBorderWhite();
    for (const dataset of data.datasets) {
        dataset.backgroundColor = colors;
        dataset.hoverBackgroundColor = colors;
        dataset.borderColor = borderColor;
        dataset.hoverOffset = 60;
    }
    let addNoDataToLegend = false;
    if (!data.datasets.length) {
        const fakeData = new Array(data.labels.length + 1);
        fakeData[data.labels.length] = 1;
        const fakeTrueLabels = new Array(data.labels.length + 1);
        fakeTrueLabels[data.labels.length] = NO_DATA;
        data.datasets.push({
            label: "",
            data: fakeData,
            trueLabels: fakeTrueLabels,
            backgroundColor: [...colors, noDataColor()],
            borderColor,
        });
        addNoDataToLegend = true;
    }
    if (addNoDataToLegend) {
        data.labels.push(NO_DATA);
    }

    return data;
}

/**
 * @param {Object} data
 * @returns {Object}
 */
export function styleScatterChartData(data) {
    for (let index = 0; index < data.datasets.length; ++index) {
        const dataset = data.datasets[index];
        const itemColor = getColor(index, data.datasets.length);
        dataset.showLine = false;
        dataset.backgroundColor = itemColor;
        dataset.borderColor = itemColor;
        dataset.borderWidth = 2;
        dataset.pointRadius = 5;
        dataset.pointHoverRadius = 8;
        dataset.pointHitRadius = 10;
        dataset.pointBackgroundColor = itemColor;
        dataset.pointBorderColor = getCustomColor(
            lightenColor(itemColor, 0.3),
            darkenColor(itemColor, 0.3),
        );
    }
    return data;
}

/**
 * @param {string} mode
 * @param {number} labelsCount
 * @returns {Record<string, any>}
 */
export function buildAnimationOptions(mode, labelsCount) {
    let delayed;
    const gap = 350;
    /** @type {Record<string, any>} */
    const animationOptions = {};
    if (mode === "pie") {
        animationOptions.offset = { duration: 200 };
    } else {
        animationOptions.duration = 600;
        animationOptions.onComplete = () => {
            delayed = true;
        };
        animationOptions.delay = (context) => {
            let delay = 0;
            if (
                (mode === "bar" || mode === "line" || mode === "scatter") &&
                !delayed &&
                labelsCount
            ) {
                delay = context.dataIndex * (gap / labelsCount);
            }
            return delay;
        };
    }
    return animationOptions;
}

/**
 * @param {string} mode
 * @param {boolean} stacked
 * @returns {Object}
 */
export function buildElementOptions(mode, stacked) {
    const elementOptions = {};
    if (mode === "bar") {
        elementOptions.bar = { borderWidth: 1 };
    } else if (mode === "line") {
        elementOptions.line = { fill: stacked, tension: 0 };
    } else if (mode === "scatter") {
        elementOptions.point = { radius: 5, hoverRadius: 8 };
    }
    return elementOptions;
}

/**
 * @param {Object} data
 * @param {Object} metaData
 * @returns {Object}
 */
export function buildScaleOptions(data, metaData) {
    const { labels } = data;
    const { fieldAttrs, measure, measures, mode, stacked } = metaData;
    if (mode === "pie") {
        return {};
    }
    const xAxe = {
        type: "category",
        ticks: {
            callback: (val, index) => {
                const value = labels[index];
                return shortenLabel(value);
            },
            color: graphLabelColor(),
        },
        grid: {
            color: "transparent",
        },
        border: {
            display: false,
        },
    };
    const yAxe = {
        beginAtZero: true,
        type: "linear",
        title: {
            text: measures[measure].string,
            color: colorScheme.isDark ? getColor(15, "xl") : null,
        },
        ticks: {
            callback: (value) => formatValue(value, false, fieldAttrs[measure]?.widget),
            color: graphLabelColor(),
        },
        stacked: mode === "line" && stacked ? stacked : undefined,
        grid: {
            display: mode !== "line" && mode !== "scatter",
            color: graphGridColor(),
        },
        border: {
            display: false,
        },
        suggestedMax: 0,
        suggestedMin: 0,
    };
    return { x: xAxe, y: yAxe };
}

/**
 * @param {Object} data
 * @param {Object} metaData
 * @param {Object} tooltipModel
 * @param {Object} [lineOverlayDataset]
 * @returns {Object[]}
 */
export function buildTooltipItems(data, metaData, tooltipModel, lineOverlayDataset) {
    const { allIntegers, mode, groupBy, measure } = metaData;
    const sortedDataPoints = sortBy(tooltipModel.dataPoints, "raw", "desc");
    const items = [];
    for (const item of sortedDataPoints) {
        const index = /** @type {any} */ (item).dataIndex;
        const dataset =
            data.datasets[/** @type {any} */ (item).datasetIndex] || lineOverlayDataset;
        let label = dataset.trueLabels[index];
        let value = dataset.data[index];
        const measureWidget = metaData.fieldAttrs[measure]?.widget;
        if (dataset.currencyIds?.[index]) {
            value = formatMonetary(value, {
                currencyId: dataset.currencyIds[index],
            });
        } else if (dataset.currencyIds?.[index] === false) {
            value = markup`${formatMonetary(value)}<sup class="ms-1 fw-bolder">?</sup>`;
        } else {
            value = formatValue(value, allIntegers, measureWidget);
        }
        let boxColor;
        let percentage;
        if (mode === "pie") {
            if (label === NO_DATA) {
                value = formatValue(0, allIntegers, measureWidget);
            }
            boxColor = dataset.backgroundColor[index];
            const totalData = dataset.data.reduce((a, b) => a + b, 0);
            percentage =
                totalData && ((dataset.data[index] * 100) / totalData).toFixed(2);
        } else {
            if (groupBy.length > 1) {
                label = `${label} / ${dataset.label}`;
            }
            boxColor =
                mode === "bar" || mode === "scatter"
                    ? dataset.backgroundColor
                    : dataset.borderColor;
        }
        items.push({ label, value, boxColor, percentage });
    }
    return items;
}

/**
 * @param {Object} chart
 * @returns {Object[]}
 */
export function generatePieLegendLabels(chart) {
    return chart.data.labels.map((label, index) => {
        const hidden = !chart.getDataVisibility(index);
        const fullText = label;
        const text = shortenLabel(fullText);
        const fillStyle =
            label === NO_DATA
                ? noDataColor()
                : getColor(index, chart.data.labels.length);
        return {
            text,
            fullText,
            fillStyle,
            hidden,
            index,
            fontColor: graphLegendColor(),
            lineWidth: 0,
        };
    });
}

/**
 * @param {Object} chart
 * @param {string} mode
 * @returns {Object[]}
 */
export function generateBarLineLegendLabels(chart, mode) {
    const referenceColor = mode === "bar" ? "backgroundColor" : "borderColor";
    const { data } = chart;
    return data.datasets.map((dataset, index) => ({
        text: shortenLabel(dataset.label),
        fullText: dataset.label,
        fillStyle: dataset[referenceColor],
        hidden: !chart.isDatasetVisible(index),
        lineCap: dataset.borderCapStyle,
        lineDash: dataset.borderDash,
        lineDashOffset: dataset.borderDashOffset,
        lineJoin: dataset.borderJoinStyle,
        lineWidth: dataset.borderWidth,
        strokeStyle: dataset[referenceColor],
        pointStyle: dataset.pointStyle,
        datasetIndex: index,
        fontColor: graphLegendColor(),
    }));
}
