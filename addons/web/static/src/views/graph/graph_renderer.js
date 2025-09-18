// @ts-check

/** @module @web/views/graph/graph_renderer - Chart.js integration for rendering bar, line, and pie charts with tooltips and legends */

import {
    Component,
    onWillStart,
    onWillUnmount,
    useEffect,
    useRef,
} from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { createElementWithContent } from "@web/core/utils/dom/html";
import { useService } from "@web/core/utils/hooks";
import { renderToMarkup } from "@web/core/utils/render";
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
} from "./graph_chart_config";

export class GraphRenderer extends Component {
    static template = "web.GraphRenderer";
    static components = { Dropdown, DropdownItem, ReportViewMeasures, Widget };
    static props = ["class?", "model", "buttonTemplate"];

    setup() {
        this.model = this.props.model;

        this.rootRef = useRef("root");
        this.canvasRef = useRef("canvas");
        this.containerRef = useRef("container");
        this.actionService = useService("action");

        this.chart = null;
        this.tooltip = null;
        this.legendTooltip = null;

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
        });

        useEffect(() => this.renderChart());
        onWillUnmount(this.onWillUnmount);
    }

    onWillUnmount() {
        if (this.chart) {
            this.chart.destroy();
        }
    }

    /**
     * This function aims to remove a suitable number of lines from the
     * tooltip in order to make it reasonably visible. A message indicating
     * the number of lines is added if necessary.
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
        if (tooltipModel.opacity === 0 || tooltipModel.dataPoints.length === 0) {
            return;
        }
        if (!disableLinking && mode !== "line") {
            this.containerRef.el.style.cursor = "pointer";
        }
        const chartAreaTop = this.chart.chartArea.top;
        const viewContentTop = this.containerRef.el.getBoundingClientRect().top;
        const content = renderToMarkup("web.GraphRenderer.CustomTooltip", {
            maxWidth: getMaxWidth(this.chart.chartArea),
            measure: measures[measure].string,
            mode: this.model.metaData.mode,
            tooltipItems: buildTooltipItems(data, metaData, tooltipModel, this.model.lineOverlayDataset),
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
            // Here we know that the full tooltip can fit in the screen.
            // We put it in the position where Chart.js would put it
            // if two conditions are respected:
            //  1: the tooltip is not cut (because we know it is possible to not cut it)
            //  2: the tooltip does not hide the legend.
            // If it is not possible to use the Chart.js proposition (y)
            // we use the best approximated value.
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
            // Here we know that we cannot satisfy condition 1 above,
            // so we position the tooltip at the minimal position and
            // cut it the minimum possible.
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
        return styleBarChartData(this.model.data, this.model.metaData, this.model.lineOverlayDataset);
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
        }
        const options = this.prepareOptions();
        const config = { data, options, type: mode };
        if (mode === "line") {
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
        if (mode === "line") {
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
        if (disableLinking || mode === "line") {
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
     * If the text of a legend item has been shortened and the user mouse
     * hovers that item (actually the event type is mousemove), a tooltip
     * with the item full text is displayed.
     * @param {Event} ev
     * @param {Object} legendItem
     */
    onLegendHover(ev, legendItem) {
        ev = /** @type {any} */ (ev).native;
        this.canvasRef.el.style.cursor = "pointer";
        /**
         * The string legendItem.text is an initial segment of legendItem.fullText.
         * If the two coincide, no need to generate a tooltip. If a tooltip
         * for the legend already exists, it is already good and does not
         * need to be recreated.
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

    /**
     * If there's a legend tooltip and the user mouse out of the
     * corresponding legend item, the tooltip is removed.
     */
    onLegendLeave() {
        this.canvasRef.el.style.cursor = "";
        this.removeLegendTooltip();
    }

    /**
     * Prepares options for the chart according to the current mode
     * (= chart type). This function returns the parameter options used to
     * instantiate the chart.
     */
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

    /**
     * Removes the legend tooltip (if any).
     */
    removeLegendTooltip() {
        if (this.legendTooltip) {
            this.legendTooltip.remove();
            this.legendTooltip = null;
        }
    }

    /**
     * Removes all existing tooltips (if any).
     */
    removeTooltips() {
        if (this.tooltip) {
            this.tooltip.remove();
            this.tooltip = null;
        }
        this.removeLegendTooltip();
    }

    /**
     * Instantiates a Chart (Chart.js lib) to render the graph according to
     * the current config.
     */
    renderChart() {
        if (this.chart) {
            this.chart.destroy();
        }
        if (this.canvasRef.el) {
            const config = this.getChartConfig();
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
        const { context } = this.model.metaData;

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
     * @param {"bar"|"line"|"pie"} mode
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
