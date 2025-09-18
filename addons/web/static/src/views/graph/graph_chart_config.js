// @ts-check

/** @module @web/views/graph/graph_chart_config - Pure chart configuration building extracted from GraphRenderer */

/**
 * Chart.js data styling, option building, and label generation for
 * bar, line, and pie chart modes. All functions are pure — they depend
 * only on model data/metaData, not on component state or DOM.
 */

import { markup } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import {
    darkenColor,
    DEFAULT_BG,
    getBorderWhite,
    getColor,
    getCustomColor,
    lightenColor,
} from "@web/core/colors/colors";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { sortBy } from "@web/core/utils/collections/arrays";
import { formatFloat, formatMonetary } from "@web/fields/formatters";

import { SEP } from "./graph_model";

const NO_DATA = _t("No data");
const fmtRegistry = registry.category("formatters");

const colorScheme = cookie.get("color_scheme");
const GRAPH_LEGEND_COLOR = getCustomColor(colorScheme, "#111827", "#ffffff");
const GRAPH_GRID_COLOR = getCustomColor(
    colorScheme,
    "rgba(0,0,0,.1)",
    "rgba(255,255,255,.15)",
);
const GRAPH_LABEL_COLOR = getCustomColor(colorScheme, "#111827", "#E4E4E4");
const NO_DATA_COLOR = getCustomColor(colorScheme, DEFAULT_BG, "#3C3E4B");

/**
 * Custom Plugin for Line chart:
 * Draw the scale grid on top of the chart to
 * see this last one correctly.
 */
export const gridOnTop = {
    id: "gridOnTop",
    afterDraw: (chart) => {
        const elements = chart.getDatasetMeta(0).data || [];
        const ctx = chart.ctx;
        const chartArea = chart.chartArea;
        const yAxis = chart.scales.y;
        const xAxis = chart.scales.x;

        ctx.lineWidth = 1;
        ctx.strokeStyle = GRAPH_GRID_COLOR;

        // Draw Y axis scale
        yAxis.ticks.forEach((value, index) => {
            const y = yAxis.getPixelForTick(index);
            ctx.beginPath();
            // Draw the line scale
            ctx.moveTo(chartArea.left, y);
            ctx.lineTo(chartArea.right, y);
            // Draw the tick mark
            ctx.moveTo(chartArea.left - 8, y);
            ctx.lineTo(chartArea.left, y);
            ctx.setLineDash([]);
            ctx.stroke();
        });

        // Draw X axis tick marks
        xAxis.ticks.forEach((value, tickIndex) => {
            const x = xAxis.getPixelForTick(tickIndex);
            ctx.beginPath();
            ctx.moveTo(x, chartArea.bottom);
            ctx.lineTo(x, chartArea.bottom + 8);
            ctx.stroke();
        });

        // Draw the X axis dashed line
        elements.forEach((point, eltIndex) => {
            xAxis.ticks.forEach((value, tickIndex) => {
                if (point.active && eltIndex === tickIndex) {
                    const x = xAxis.getPixelForTick(tickIndex);
                    ctx.beginPath();
                    ctx.moveTo(x, chartArea.top);
                    ctx.lineTo(x, chartArea.bottom);
                    ctx.strokeStyle = GRAPH_GRID_COLOR;
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
 * Used to avoid too long legend items.
 * @param {string} label
 * @returns {string} shortened version of the input label
 */
function shortenLabel(label) {
    // string returned could be wrong if a groupby value contain a " / "!
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
 * Format a value for display in tooltips and Y axis labels.
 * @param {number} value
 * @param {boolean} [allIntegers=true]
 * @param {string} [formatType=""]
 * @returns {string}
 */
function formatValue(value, allIntegers = true, formatType = "") {
    const largeNumber = Math.abs(value) >= 1000;
    if (formatType) {
        return fmtRegistry.get(formatType)(value);
    }
    if (allIntegers && !largeNumber) {
        return String(value);
    }
    if (largeNumber) {
        return formatFloat(value, {
            humanReadable: true,
            decimals: 2,
            minDigits: 1,
        });
    }
    return formatFloat(value);
}

/* --------------------------------------------------------
 * Chart data styling
 * -------------------------------------------------------- */

/**
 * Style bar chart datasets with colors and optional stacking/line overlay.
 * @param {Object} data
 * @param {Object} metaData
 * @param {Object} [lineOverlayDataset]
 * @returns {Object}
 */
export function styleBarChartData(data, metaData, lineOverlayDataset) {
    const { stacked } = metaData;
    for (let index = 0; index < data.datasets.length; ++index) {
        const dataset = data.datasets[index];
        const itemColor = getColor(index, colorScheme, data.datasets.length);
        // used when stacked
        if (stacked) {
            dataset.stack = "";
        }
        // set dataset color
        dataset.backgroundColor = itemColor;
        dataset.borderRadius = 4;
    }
    if (lineOverlayDataset) {
        // Mutate the lineOverlayDataset to include the config on how it will be displayed.
        Object.assign(lineOverlayDataset, {
            type: "line",
            order: -1,
            tension: 0,
            fill: false,
            pointHitRadius: 20,
            pointRadius: 5,
            pointHoverRadius: 10,
            backgroundColor: getCustomColor(colorScheme, "#343a40", "#e9ecef"),
            borderColor: getCustomColor(
                colorScheme,
                "rgba(0,0,0,.3)",
                "rgba(255,255,255,.5)",
            ),
            borderWidth: 2,
            lineWidth: 3,
        });
        // We're not mutating the original datasets (`this.model.data.datasets`)
        // because some part of the code depends on it.
        return {
            ...data,
            datasets: [...data.datasets, lineOverlayDataset],
        };
    }

    return data;
}

/**
 * Style line chart datasets with colors, cumulation, and single-point centering.
 * @param {Object} data
 * @param {Object} metaData
 * @returns {Object}
 */
export function styleLineChartData(data, metaData) {
    const { cumulated } = metaData;
    for (let index = 0; index < data.datasets.length; ++index) {
        const dataset = data.datasets[index];
        const itemColor = getColor(index, colorScheme, data.datasets.length);
        dataset.backgroundColor = getCustomColor(
            colorScheme,
            lightenColor(itemColor, 0.5),
            darkenColor(itemColor, 0.5),
        );
        dataset.cubicInterpolationMode = "monotone";
        dataset.borderColor = itemColor;
        dataset.borderWidth = 2;
        dataset.hoverBackgroundColor = dataset.borderColor;
        dataset.pointRadius = 3;
        dataset.pointHoverRadius = 6;
        if (cumulated) {
            let accumulator = dataset.cumulatedStart;
            dataset.data = dataset.data.map((value) => {
                accumulator += value;
                return accumulator;
            });
        }
        if (data.labels.length === 1) {
            // shift of the real value to right. This is done to
            // center the points in the chart. See data.labels below in
            // Chart parameters
            dataset.data.unshift(undefined);
            dataset.trueLabels.unshift(undefined);
            dataset.domains.unshift(undefined);
        }
        dataset.pointBackgroundColor = dataset.borderColor;
    }
    // center the points in the chart (without that code they are put
    // on the left and the graph seems empty)
    data.labels = data.labels.length > 1 ? data.labels : ["", ...data.labels, ""];
    return data;
}

/**
 * Style pie chart datasets with colors, borders, and no-data fallback.
 * @param {Object} data
 * @returns {Object}
 */
export function stylePieChartData(data) {
    // style/complete data
    // give same color to same groups from different origins
    const colors = data.labels.map((_, index) =>
        getColor(index, colorScheme, data.labels.length),
    );
    const borderColor = getBorderWhite(colorScheme);
    for (const dataset of data.datasets) {
        dataset.backgroundColor = colors;
        dataset.hoverBackgroundColor = colors;
        dataset.borderColor = borderColor;
        dataset.hoverOffset = 60;
    }
    let addNoDataToLegend = false;
    if (data.datasets.length === 0) {
        const fakeData = new Array(data.labels.length + 1);
        fakeData[data.labels.length] = 1;
        const fakeTrueLabels = new Array(data.labels.length + 1);
        fakeTrueLabels[data.labels.length] = NO_DATA;
        data.datasets.push({
            label: "",
            data: fakeData,
            trueLabels: fakeTrueLabels,
            backgroundColor: [...colors, NO_DATA_COLOR],
            borderColor,
        });
        addNoDataToLegend = true;
    }
    if (addNoDataToLegend) {
        data.labels.push(NO_DATA);
    }

    return data;
}

/* --------------------------------------------------------
 * Chart option builders
 * -------------------------------------------------------- */

/**
 * Build animation options with progressive animation for bar/line and reduced duration for pie.
 * @param {string} mode
 * @param {number} labelsCount
 * @returns {Object}
 */
export function buildAnimationOptions(mode, labelsCount) {
    let delayed;
    const gap = 350;
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
            if ((mode === "bar" || mode === "line") && !delayed) {
                delay = context.dataIndex * (gap / labelsCount);
            }
            return delay;
        };
    }
    return animationOptions;
}

/**
 * Build element styling options independent from datasets.
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
    }
    return elementOptions;
}

/**
 * Build X/Y axis scale options.
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
            color: GRAPH_LABEL_COLOR,
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
            color:
                cookie.get("color_scheme") === "dark"
                    ? getColor(15, cookie.get("color_scheme"))
                    : null,
        },
        ticks: {
            callback: (value) =>
                formatValue(value, false, fieldAttrs[measure]?.widget),
            color: GRAPH_LABEL_COLOR,
        },
        stacked: mode === "line" && stacked ? stacked : undefined,
        grid: {
            display: mode !== "line",
            color: GRAPH_GRID_COLOR,
        },
        border: {
            display: false,
        },
        suggestedMax: 0,
        suggestedMin: 0,
    };
    return { x: xAxe, y: yAxe };
}

/* --------------------------------------------------------
 * Tooltip data extraction
 * -------------------------------------------------------- */

/**
 * Extract tooltip item data from Chart.js datapoints.
 * @param {Object} data
 * @param {Object} metaData
 * @param {Object} tooltipModel — Chart.js tooltip model
 * @param {Object} [lineOverlayDataset]
 * @returns {Object[]}
 */
export function buildTooltipItems(data, metaData, tooltipModel, lineOverlayDataset) {
    const { allIntegers, mode, groupBy, measure } = metaData;
    const sortedDataPoints = sortBy(tooltipModel.dataPoints, "raw", "desc");
    const items = [];
    for (const item of sortedDataPoints) {
        const index = /** @type {any} */ (item).dataIndex;
        // If `datasetIndex` is not found in the `datasets`, then it refers to the `lineOverlayDataset`.
        const dataset =
            data.datasets[/** @type {any} */ (item).datasetIndex] ||
            lineOverlayDataset;
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
                mode === "bar" ? dataset.backgroundColor : dataset.borderColor;
        }
        items.push({ label, value, boxColor, percentage });
    }
    return items;
}

/* --------------------------------------------------------
 * Legend label generators
 * -------------------------------------------------------- */

/**
 * Generate legend labels for pie charts.
 * @param {Object} chart — Chart.js instance
 * @returns {Object[]}
 */
export function generatePieLegendLabels(chart) {
    return chart.data.labels.map((label, index) => {
        const hidden = !chart.getDataVisibility(index);
        const fullText = label;
        const text = shortenLabel(fullText);
        const fillStyle =
            label === NO_DATA
                ? NO_DATA_COLOR
                : getColor(index, colorScheme, chart.data.labels.length);
        return {
            text,
            fullText,
            fillStyle,
            hidden,
            index,
            fontColor: GRAPH_LEGEND_COLOR,
            lineWidth: 0,
        };
    });
}

/**
 * Generate legend labels for bar and line charts.
 * @param {Object} chart — Chart.js instance
 * @param {string} mode — "bar" or "line"
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
        fontColor: GRAPH_LEGEND_COLOR,
    }));
}
