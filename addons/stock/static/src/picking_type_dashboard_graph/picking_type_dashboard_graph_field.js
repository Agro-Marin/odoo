/** @odoo-module native */
import { readJsonField } from "@stock/utils/json_field";
import { getColor, getCustomColor } from "@web/core/colors/colors";
import { Chart } from "@web/core/lib/chartjs";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { JournalDashboardGraphField } from "@web/fields/specialized/journal_dashboard_graph/journal_dashboard_graph_field";

/**
 * The search filter each bar stands for, by position, for payloads that predate
 * `values[].category`. Positional and therefore fragile, which is why the
 * per-value `category` is preferred wherever the server sends one.
 */
const BAR_CATEGORIES = ["before", "yesterday", "today", "day_1", "day_2", "after"];

/**
 * Heights for the placeholder bars an all-sample dashboard draws.
 *
 * This was `Math.random()`, which put a generator in a render path: the same
 * card drew a different shape on every reload, and nothing about it could be
 * asserted. Hashing the record and the bar index gives the same visual variety
 * and the same picture twice.
 */
export function shapeSampleBars(values, seed = 0) {
    values.forEach((value, index) => {
        value.value = ((Math.imul(seed + index + 1, 2654435761) >>> 0) % 9) + 1;
    });
}

export class PickingTypeDashboardGraphField extends JournalDashboardGraphField {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
            // Chart.js tolerates a second destroy, but leaving a destroyed
            // instance reachable makes `if (this.chart)` mean nothing.
            this.chart = null;
        }
        this.data = this.getGraphData();
        if (!this.data.length) {
            return;
        }
        let config;
        if (this.props.graphType === "line") {
            config = this.getLineChartConfig();
        } else {
            config = this.getBarChartConfig();
        }
        this.chart = new Chart(this.canvasRef.el, config);
    }

    getGraphData() {
        const raw = this.props.record.data[this.props.name];
        if (this._graphRaw !== raw) {
            this._graphRaw = raw;
            const parsed = readJsonField(this, []);
            const data = Array.isArray(parsed) ? parsed : [];
            if (
                data[0]?.values?.length &&
                data[0].values.every((value) => value.type === "sample") &&
                this.env.stockDashboardAllSample?.()
            ) {
                shapeSampleBars(data[0].values, this.props.record.resId);
            }
            this._graphData = data;
        }
        return this._graphData;
    }

    /** Values, labels and per-bar colours, in one pass over the series. */
    _barSeries() {
        const byType = {
            past: getColor(8),
            present: getColor(16),
            future: getColor(12),
        };
        const data = [];
        const labels = [];
        const backgroundColor = [];
        for (const point of this.data[0].values) {
            data.push(point.value);
            labels.push(point.label);
            backgroundColor.push(
                byType[point.type] ?? getCustomColor("#ebebeb", "#3C3E4B"),
            );
        }
        return { data, labels, backgroundColor };
    }

    /** The search filter a clicked bar stands for. */
    _categoryOfBar(columnIndex) {
        return (
            this.data[0].values?.[columnIndex]?.category ?? BAR_CATEGORIES[columnIndex]
        );
    }

    _onBarClick(elements) {
        const pickingTypeId = this.data[0].picking_type_id;
        if (!pickingTypeId || !elements.length) {
            return;
        }
        const dateCategory = this._categoryOfBar(elements[0].index);
        if (!dateCategory) {
            return;
        }
        this.actionService.doAction("stock.click_dashboard_graph", {
            additionalContext: {
                picking_type_id: pickingTypeId,
                search_default_picking_type_id: [pickingTypeId],
                [`search_default_${dateCategory}`]: true,
            },
        });
    }

    get _isAllSample() {
        return Boolean(this.data[0]?.values?.every((value) => value.type === "sample"));
    }

    getBarChartConfig() {
        const { data, labels, backgroundColor } = this._barSeries();
        return {
            type: "bar",
            data: {
                labels,
                datasets: [
                    { backgroundColor, data, fill: "start", label: this.data[0].key },
                ],
            },
            options: {
                onClick: (ev, elements) => this._onBarClick(elements),
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        // Placeholder bars carry no real figure to show.
                        enabled: !this._isAllSample,
                        intersect: false,
                        position: "nearest",
                        caretSize: 0,
                    },
                },
                scales: { y: { display: false }, x: { display: false } },
                maintainAspectRatio: false,
                elements: { line: { tension: 0.000001 } },
            },
        };
    }
}

export const pickingTypeDashboardGraphField = {
    component: PickingTypeDashboardGraphField,
    supportedTypes: ["text"],
    extractProps: ({ attrs }) => ({
        graphType: attrs.graph_type,
    }),
};

registry
    .category("fields")
    .add("picking_type_dashboard_graph", pickingTypeDashboardGraphField);
