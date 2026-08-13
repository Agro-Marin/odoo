/** @odoo-module native */
import { getColor, getCustomColor } from "@web/core/colors/colors";
import { Chart } from "@web/core/lib/chartjs";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { JournalDashboardGraphField } from "@web/fields/specialized/journal_dashboard_graph/journal_dashboard_graph_field";

export class PickingTypeDashboardGraphField extends JournalDashboardGraphField {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
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
        const raw = this.props.record.data[this.props.name] || "[]";
        if (this._graphRaw !== raw) {
            this._graphRaw = raw;
            let data;
            try {
                data = JSON.parse(raw);
            } catch {
                data = [];
            }
            if (!Array.isArray(data)) {
                data = [];
            }
            if (
                data[0]?.values?.length &&
                data[0].values.every((value) => value.type === "sample") &&
                this.env.stockDashboardAllSample?.()
            ) {
                for (const value of data[0].values) {
                    value.value = Math.floor(Math.random() * 9 + 1);
                }
            }
            this._graphData = data;
        }
        return this._graphData;
    }

    getBarChartConfig() {
        const data = [];
        const labels = [];
        const backgroundColor = [];

        const colorPast = getColor(8);
        const colorPresent = getColor(16);
        const colorFuture = getColor(12);
        this.data[0].values.forEach((pt) => {
            data.push(pt.value);
            labels.push(pt.label);
            if (pt.type === "past") {
                backgroundColor.push(colorPast);
            } else if (pt.type === "present") {
                backgroundColor.push(colorPresent);
            } else if (pt.type === "future") {
                backgroundColor.push(colorFuture);
            } else {
                backgroundColor.push(
                    getCustomColor("#ebebeb", "#3C3E4B"),
                );
            }
        });
        return {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        backgroundColor,
                        data,
                        fill: "start",
                        label: this.data[0].key,
                    },
                ],
            },
            options: {
                onClick: (e, elements) => {
                    const pickingTypeId = this.data[0].picking_type_id;
                    if (!pickingTypeId || !elements.length) {
                        return;
                    }
                    const columnIndex = elements[0].index;
                    const dateCategories = {
                        0: "before",
                        1: "yesterday",
                        2: "today",
                        3: "day_1",
                        4: "day_2",
                        5: "after",
                    };
                    const dateCategory =
                        this.data[0].values?.[columnIndex]?.category ??
                        dateCategories[columnIndex];
                    if (!dateCategory) {
                        return;
                    }
                    const additionalContext = {
                        picking_type_id: pickingTypeId,
                        search_default_picking_type_id: [pickingTypeId],
                    };
                    additionalContext["search_default_".concat(dateCategory)] = true;
                    this.actionService.doAction("stock.click_dashboard_graph", {
                        additionalContext: additionalContext,
                    });
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: !this.data[0]?.values?.every(
                            (value) => value.type === "sample",
                        ),
                        intersect: false,
                        position: "nearest",
                        caretSize: 0,
                    },
                },
                scales: {
                    y: {
                        display: false,
                    },
                    x: {
                        display: false,
                    },
                },
                maintainAspectRatio: false,
                elements: {
                    line: {
                        tension: 0.000001,
                    },
                },
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
