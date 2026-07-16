// @ts-check
/** @odoo-module native */

/** @module @web/views/graph/graph_renderer - Chart.js integration for rendering bar, line, pie, and scatter charts with tooltips and legends */

import { Component, onWillStart, onWillUnmount, useEffect, useRef } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { Chart, loadChartJS } from "@web/core/lib/chartjs";
import { createElementWithContent } from "@web/core/utils/dom/html";
import { useService } from "@web/core/utils/hooks";
import { renderToMarkup } from "@web/core/utils/render";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { useReactiveModel } from "@web/model/model";
import { ReportViewMeasures } from "@web/views/view_components/report_view_measures";
import { Widget } from "@web/views/widgets/widget";

import {
    buildAnimationOptions,
    buildElementOptions,
    buildScaleOptions,
    buildTooltipItems,
    generateBarLineLegendLabels,
    generatePieLegendLabels,
    getMaxWidth,
    gridOnTop,
    styleBarChartData,
    styleLineChartData,
    stylePieChartData,
    styleScatterChartData,
} from "./graph_chart_config.js";

export class GraphRenderer extends Component {
    static template = "web.GraphRenderer";
    static components = { Dropdown, DropdownItem, ReportViewMeasures, Widget };
    static props = ["class?", "model", "buttonTemplate"];

    setup() {
        useRenderCounter("graph.GraphRenderer");
        // Subscribe directly to model.notify(): the model prop is stable,
        // so this renderer only re-rendered (and re-evaluated the chart
        // effect deps below) through the legacy deep-render listener
        // before (GraphModel now opts out via ``reactiveRenderers``).
        this.model = useReactiveModel(this.props.model);

        this.rootRef = useRef("root");
        this.canvasRef = useRef("canvas");
        this.containerRef = useRef("container");
        this.actionService = useService("action");

        this.chart = null;
        this.tooltip = null;
        this.legendTooltip = null;

        onWillStart(async () => {
            await loadChartJS();
        });

        // Rebuild the (heavyweight) Chart.js instance only when inputs that define
        // the chart change; without a deps array this re-ran (re-parsing config,
        // replaying entry animations) on every render. GraphModel reassigns
        // `data`/`metaData` (and recomputes lineOverlayDataset alongside `data`) on
        // every load/config change, so these two deps capture every real change.
        useEffect(
            () => this.renderChart(),
            () => [this.model.data, this.model.metaData],
        );
        onWillUnmount(this.onWillUnmount);
    }

    onWillUnmount() {
        if (this.chart) {
            this.chart.destroy();
        }
    }

    /**
     * Remove enough tooltip lines to keep it reasonably visible, appending a
     * "..." indicator if any were removed.
     * @param {HTMLElement} tooltip
     * @param {number} maxTooltipHeight this the max height in pixels of the tooltip
     */
    adjustTooltipHeight(tooltip, maxTooltipHeight) {
        const sizeOneLine = tooltip.querySelector("tbody tr").clientHeight;
        const tbodySize = tooltip.querySelector("tbody").clientHeight;
        const toKeep = Math.max(
            0,
            Math.floor(
                (maxTooltipHeight - (tooltip.clientHeight - tbodySize)) / sizeOneLine,
            ) - 1,
        );
        const lines = tooltip.querySelectorAll("tbody tr");
        const toRemove = lines.length - toKeep;
        if (toRemove > 0) {
            for (let index = toKeep; index < lines.length; ++index) {
                lines[index].remove();
            }
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            tr.classList.add("o_show_more", "text-center", "fw-bold");
            td.setAttribute("colspan", "2");
            td.innerText = _t("...");
            tr.appendChild(td);
            tooltip.querySelector("tbody").appendChild(tr);
        }
    }

    /**
     * Creates a custom HTML tooltip.
     * @param {Object} data
     * @param {Object} metaData
     * @param {Object} context see chartjs documentation
     */
    customTooltip(data, metaData, context) {
        const tooltipModel = context.tooltip;
        const { measure, measures, disableLinking, mode } = metaData;
        this.containerRef.el.style.cursor = "";
        this.removeTooltips();
        if (tooltipModel.opacity === 0 || !tooltipModel.dataPoints.length) {
            return;
        }
        if (!disableLinking && mode !== "line" && mode !== "scatter") {
            this.containerRef.el.style.cursor = "pointer";
        }
        const chartAreaTop = this.chart.chartArea.top;
        const viewContentTop = this.containerRef.el.getBoundingClientRect().top;
        const content = renderToMarkup("web.GraphRenderer.CustomTooltip", {
            maxWidth: getMaxWidth(this.chart.chartArea),
            measure: measures[measure].string,
            mode: this.model.metaData.mode,
            tooltipItems: buildTooltipItems(
                data,
                metaData,
                tooltipModel,
                this.model.lineOverlayDataset,
            ),
        });
        const template = createElementWithContent("template", content);
        const tooltip = /** @type {HTMLElement} */ (
            /** @type {HTMLTemplateElement} */ (template).content.firstChild
        );
        this.containerRef.el.prepend(tooltip);

        let top;
        const tooltipHeight = tooltip.clientHeight;
        const minTopAllowed = Math.floor(chartAreaTop);
        const maxTopAllowed =
            Math.floor(window.innerHeight - (viewContentTop + tooltipHeight)) - 2;
        const y = Math.floor(tooltipModel.y);
        if (minTopAllowed <= maxTopAllowed) {
            // The tooltip fits on screen: position it where Chart.js proposes (y)
            // if that keeps it uncut and not hiding the legend; otherwise clamp to
            // the closest allowed value.
            if (y <= maxTopAllowed) {
                if (y >= minTopAllowed) {
                    top = y;
                } else {
                    top = minTopAllowed;
                }
            } else {
                top = maxTopAllowed;
            }
        } else {
            // Cannot avoid cutting the tooltip: position it at the minimum and
            // trim as little as possible.
            top = minTopAllowed;
            const maxTooltipHeight =
                window.innerHeight - (viewContentTop + chartAreaTop) - 2;
            this.adjustTooltipHeight(tooltip, maxTooltipHeight);
        }
        this.fixTooltipLeftPosition(tooltip, tooltipModel.x);
        tooltip.style.top = `${Math.floor(top)}px`;

        this.tooltip = tooltip;
    }

    /**
     * Sets best left position of a tooltip approaching the proposal x.
     * @param {HTMLElement} tooltip
     * @param {number} x
     */
    fixTooltipLeftPosition(tooltip, x) {
        let left;
        const tooltipWidth = tooltip.clientWidth;
        const minLeftAllowed = Math.floor(this.chart.chartArea.left + 2);
        const maxLeftAllowed = Math.floor(
            this.chart.chartArea.right - tooltipWidth - 2,
        );
        x = Math.floor(x);
        if (x < minLeftAllowed) {
            left = minLeftAllowed;
        } else if (x > maxLeftAllowed) {
            left = maxLeftAllowed;
        } else {
            left = x;
        }
        tooltip.style.left = `${left}px`;
    }

    /**
     * Returns the bar chart data
     * @returns {Object}
     */
    getBarChartData() {
        return styleBarChartData(
            this.model.data,
            this.model.metaData,
            this.model.lineOverlayDataset,
        );
    }

    /**
     * Returns the chart config.
     * @returns {Object}
     */
    getChartConfig() {
        const { mode } = this.model.metaData;
        let data;
        switch (mode) {
            case "bar":
                data = this.getBarChartData();
                break;
            case "line":
                data = this.getLineChartData();
                break;
            case "pie":
                data = this.getPieChartData();
                break;
            case "scatter":
                data = this.getScatterChartData();
                break;
        }
        const options = this.prepareOptions();
        // Scatter is rendered as a line chart with showLine:false on each dataset
        const type = mode === "scatter" ? "line" : mode;
        const config = { data, options, type };
        if (mode === "line" || mode === "scatter") {
            config.plugins = [gridOnTop];
        }
        return config;
    }

    /**
     * @returns {Object}
     */
    getLegendOptions() {
        const { mode } = this.model.metaData;
        const legendOptions = {
            onHover: this.onLegendHover.bind(this),
            onLeave: this.onLegendLeave.bind(this),
        };
        if (mode === "line" || mode === "scatter") {
            legendOptions.onClick = this.onLegendClick.bind(this);
        }
        if (mode === "pie") {
            legendOptions.labels = {
                generateLabels: generatePieLegendLabels,
            };
        } else {
            legendOptions.position = "top";
            legendOptions.align = "end";
            legendOptions.labels = {
                generateLabels: (chart) => generateBarLineLegendLabels(chart, mode),
            };
        }
        return legendOptions;
    }

    /**
     * Returns line chart data.
     * @returns {Object}
     */
    getLineChartData() {
        return styleLineChartData(this.model.data, this.model.metaData);
    }

    /**
     * Returns pie chart data.
     * @returns {Object}
     */
    getPieChartData() {
        return stylePieChartData(this.model.data);
    }

    /**
     * Returns scatter chart data (line chart with showLine:false).
     * @returns {Object}
     */
    getScatterChartData() {
        return styleScatterChartData(this.model.data);
    }

    /**
     * Returns the options used to generate the chart axes.
     * @returns {Object}
     */
    getScaleOptions() {
        return buildScaleOptions(this.model.data, this.model.metaData);
    }

    loadAll() {
        return this.model.forceLoadAll();
    }

    /**
     * Returns the options used to generate chart tooltips.
     * @returns {Object}
     */
    getTooltipOptions() {
        const { data, metaData } = this.model;
        const { mode } = metaData;
        const tooltipOptions = {
            enabled: false,
            external: this.customTooltip.bind(this, data, metaData),
        };
        if (mode === "line") {
            tooltipOptions.mode = "index";
            tooltipOptions.intersect = false;
            tooltipOptions.position = "average";
        }
        if (mode === "scatter") {
            tooltipOptions.mode = "nearest";
            tooltipOptions.intersect = true;
        }
        if (mode === "bar") {
            tooltipOptions.xAlign = "center";
            tooltipOptions.yAlign = "bottom";
        }
        if (mode === "pie") {
            tooltipOptions.xAlign = "center";
            tooltipOptions.yAlign = "center";
        }
        return tooltipOptions;
    }

    /**
     * If a group has been clicked on, display a view of its records.
     * @param {MouseEvent} ev
     */
    onGraphClicked(ev, isMiddleClick) {
        const { disableLinking, mode } = this.model.metaData;
        if (disableLinking || mode === "line" || mode === "scatter") {
            return;
        }
        const [activeElement] = this.chart.getElementsAtEventForMode(
            ev,
            "nearest",
            { intersect: true },
            false,
        );
        if (!activeElement) {
            return;
        }
        const { datasetIndex, index } = activeElement;
        const { domains } = this.chart.data.datasets[datasetIndex];
        if (domains) {
            this.onGraphClickedFinal(domains[index], isMiddleClick);
        }
    }

    /**
     * Overrides the default legend 'onClick' behaviour. This is done to
     * remove all existing tooltips right before updating the chart.
     * @param {Event} ev
     * @param {Object} legendItem
     */
    onLegendClick(ev, legendItem) {
        this.removeTooltips();
        // Default 'onClick' fallback. See web/static/lib/Chart/Chart.js#15138
        const index = legendItem.datasetIndex;
        const meta = this.chart.getDatasetMeta(index);
        meta.hidden =
            meta.hidden === null ? !this.chart.data.datasets[index].hidden : null;
        this.chart.update();
    }

    /**
     * Show a tooltip with the legend item's full text when its shortened text
     * is hovered (event type is actually mousemove).
     * @param {Event} ev
     * @param {Object} legendItem
     */
    onLegendHover(ev, legendItem) {
        ev = /** @type {any} */ (ev).native;
        this.canvasRef.el.style.cursor = "pointer";
        /**
         * legendItem.text is a prefix of legendItem.fullText; skip if they
         * match (nothing to show) or a tooltip already exists (already correct).
         */
        const { fullText, text } = legendItem;
        if (this.legendTooltip || text === fullText) {
            return;
        }
        const viewContentTop = this.canvasRef.el.getBoundingClientRect().top;
        const legendTooltip = Object.assign(document.createElement("div"), {
            className: "o_tooltip_legend popover p-3 pe-none position-absolute",
            innerText: fullText,
        });
        legendTooltip.style.top = `${/** @type {MouseEvent} */ (ev).clientY - viewContentTop}px`;
        legendTooltip.style.maxWidth = getMaxWidth(this.chart.chartArea);
        this.containerRef.el.appendChild(legendTooltip);
        this.fixTooltipLeftPosition(
            legendTooltip,
            /** @type {MouseEvent} */ (ev).clientX,
        );
        this.legendTooltip = legendTooltip;
    }

    /** Remove the legend tooltip when the mouse leaves the legend item. */
    onLegendLeave() {
        this.canvasRef.el.style.cursor = "";
        this.removeLegendTooltip();
    }

    /** Build chart instantiation options for the current mode (chart type). */
    prepareOptions() {
        const { mode, stacked } = this.model.metaData;
        const options = {
            maintainAspectRatio: false,
            scales: this.getScaleOptions(),
            plugins: {
                legend: this.getLegendOptions(),
                tooltip: this.getTooltipOptions(),
            },
            elements: buildElementOptions(mode, stacked),
            onResize: () => {
                this.resizeChart(options);
            },
            animation: buildAnimationOptions(mode, this.model.data.labels.length),
        };
        if (mode === "line") {
            options.interaction = {
                mode: "index",
                intersect: false,
            };
        }
        if (mode === "scatter") {
            options.interaction = {
                mode: "nearest",
                intersect: true,
            };
        }
        if (mode === "pie") {
            options.radius = "90%";
        }
        return options;
    }

    /**
     * Adapt Pie chart layout on mobile
     * @param {Object} context
     */
    resizeChart(context) {
        const { mode } = this.model.metaData;
        if (mode === "pie") {
            if (this.env.isSmall) {
                context.plugins.legend.position = "bottom";
                context.plugins.legend.align = "center";
            } else {
                context.plugins.legend.position = "right";
                context.plugins.legend.align = "start";
            }
        }
    }

    /** Remove the legend tooltip, if any. */
    removeLegendTooltip() {
        if (this.legendTooltip) {
            this.legendTooltip.remove();
            this.legendTooltip = null;
        }
    }

    /** Remove all existing tooltips, if any. */
    removeTooltips() {
        if (this.tooltip) {
            this.tooltip.remove();
            this.tooltip = null;
        }
        this.removeLegendTooltip();
    }

    /** Instantiate or update the Chart.js chart from the current config. */
    renderChart() {
        // Tooltips are plain DOM cleaned up by the chart's own tooltip
        // callbacks; once a chart is updated or destroyed they would linger
        // over the new render until the next hover.
        this.removeTooltips();
        if (!this.canvasRef.el) {
            if (this.chart) {
                this.chart.destroy();
                this.chart = null;
            }
            return;
        }
        const config = this.getChartConfig();
        if (this.chart && this.chart.config.type === config.type) {
            // Same chart kind: update the existing instance in place instead
            // of destroy+recreate, which replayed the full entry animation on
            // every data/config change (measure toggle, sort, reload...).
            // The inline plugins are keyed on the type ("line" ⇒ [gridOnTop])
            // so an equal type implies equal plugins.
            this.chart.data = config.data;
            this.chart.options = config.options;
            this.chart.update();
        } else {
            if (this.chart) {
                this.chart.destroy();
            }
            this.chart = new Chart(this.canvasRef.el, config);
        }
    }

    /**
     * Execute the action to open the view on the current model.
     *
     * @param {Array} domain
     * @param {Array} views
     * @param {Object} context
     */
    openView(domain, views, context, newWindow) {
        this.actionService.doAction(
            {
                context,
                domain,
                name: this.model.metaData.title,
                res_model: this.model.metaData.resModel,
                search_view_id: this.env.config.views?.find((v) => v[1] === "search"),
                target: "current",
                type: "ir.actions.act_window",
                views,
            },
            {
                newWindow,
                viewType: "list",
            },
        );
    }
    /**
     * @param {any[]} domain the domain of the clicked area
     */
    onGraphClickedFinal(domain, isMiddleClick = false) {
        const context = { ...this.model.metaData.context };

        for (const x of Object.keys(context)) {
            if (x === "group_by" || x.startsWith("search_default_")) {
                delete context[x];
            }
        }

        const views = {};
        for (const [viewId, viewType] of this.env.config.views || []) {
            views[viewType] = viewId;
        }
        function getView(viewType) {
            return [views[viewType] || false, viewType];
        }
        const actionViews = [getView("list"), getView("form")];
        this.openView(domain, /** @type {any} */ (actionViews), context, isMiddleClick);
    }

    /**
     * @param {Object} param0
     * @param {string} param0.measure
     */
    onMeasureSelected({ measure }) {
        this.model.updateMetaData({ measure });
    }

    /**
     * @param {"bar"|"line"|"pie"|"scatter"} mode
     */
    onModeSelected(mode) {
        if (this.model.metaData.mode !== mode) {
            this.model.updateMetaData({ mode });
        }
    }

    /**
     * @param {"ASC"|"DESC"} order
     */
    toggleOrder(order) {
        const { order: currentOrder } = this.model.metaData;
        const nextOrder = currentOrder === order ? null : order;
        this.model.updateMetaData({ order: nextOrder });
    }

    toggleStacked() {
        const { stacked } = this.model.metaData;
        this.model.updateMetaData({ stacked: !stacked });
    }

    toggleCumulated() {
        const { cumulated } = this.model.metaData;
        this.model.updateMetaData({ cumulated: !cumulated });
    }
}
