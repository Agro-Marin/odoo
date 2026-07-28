// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/journal_dashboard_graph/journal_dashboard_graph_field - Chart.js graph field for accounting journal dashboard data */

import { Component, onWillStart, useEffect, useRef } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { getColor, getCustomColor, hexToRGBA } from "@web/core/colors/colors";
import { Chart, loadChartJS } from "@web/core/lib/chartjs";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class JournalDashboardGraphField extends Component {
    static template = "web.JournalDashboardGraphField";
    static GRAPH_TYPES = ["line", "bar"];
    static props = {
        ...standardFieldProps,
        graphType: {
            type: String,
            optional: true,
            validate: (t) => JournalDashboardGraphField.GRAPH_TYPES.includes(t),
        },
    };
    static defaultProps = {
        // `graph_type` is an arch attribute, so it is absent whenever the view
        // author forgets it — but the prop was required, which only surfaces as
        // a prop-validation error in dev. In production it left `config`
        // undefined all the way into `new Chart(el, undefined)`.
        graphType: "bar",
    };

    setup() {
        this.chart = null;
        this.canvasRef = useRef("canvas");

        onWillStart(async () => {
            await loadChartJS();
        });

        useEffect(
            () => {
                this.renderChart();
                return () => {
                    if (this.chart) {
                        this.chart.destroy();
                    }
                };
            },
            () => [this.props.record.data[this.props.name]],
        );
    }

    /** Instantiates the Chart.js chart for the current config. */
    renderChart() {
        if (this.chart) {
            this.chart.destroy();
        }
        // The payload is server-generated JSON, but a malformed one used to
        // propagate out of the effect and take down the whole view rather than
        // just blanking this tile.
        try {
            this.data = JSON.parse(this.props.record.data[this.props.name] || "[]");
        } catch (error) {
            console.error(
                `[dashboard_graph] "${this.props.name}" does not hold valid JSON; ` +
                    `rendering no graph:`,
                error,
            );
            this.data = [];
        }
        if (!Array.isArray(this.data) || !this.data.length) {
            return;
        }
        const config =
            this.props.graphType === "line"
                ? this.getLineChartConfig()
                : this.getBarChartConfig();
        this.chart = new Chart(this.canvasRef.el, config);
    }
    /** @returns {Object} Chart.js configuration object for a line chart */
    getLineChartConfig() {
        const labels = this.data[0].values.map((pt) => pt.x);
        const color10 = getColor(3, cookie.get("color_scheme"), "odoo");
        const borderColor = this.data[0].is_sample_data
            ? hexToRGBA(color10, 0.1)
            : color10;
        const backgroundColor = this.data[0].is_sample_data
            ? hexToRGBA(color10, 0.05)
            : hexToRGBA(color10, 0.2);
        return {
            type: "line",
            data: {
                labels,
                datasets: [
                    {
                        backgroundColor,
                        borderColor,
                        data: this.data[0].values,
                        fill: "start",
                        label: this.data[0].key,
                        borderWidth: 2,
                    },
                ],
            },
            options: {
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: !this.data[0].is_sample_data,
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

    getBarChartConfig() {
        const data = [];
        const labels = [];
        const backgroundColor = [];

        const colorScheme = cookie.get("color_scheme");
        const gridColor = getCustomColor(colorScheme, "#d8dadd", "#3C3E4B");
        const labelColor = getCustomColor(colorScheme, "#111827", "#E4E4E4");
        const color13 = getColor(2, colorScheme, "odoo");
        const color19 = getColor(1, colorScheme, "odoo");
        this.data[0].values.forEach((pt) => {
            data.push(pt.value);
            labels.push(pt.label);
            if (pt.type === "past") {
                backgroundColor.push(color13);
            } else if (pt.type === "future") {
                backgroundColor.push(color19);
            } else {
                backgroundColor.push(getCustomColor(colorScheme, "#ebebeb", "#3C3E4B"));
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
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: !this.data[0].is_sample_data,
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
                        grid: {
                            color: gridColor,
                        },
                        ticks: {
                            color: labelColor,
                        },
                        border: {
                            color: gridColor,
                        },
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

export const journalDashboardGraphField = {
    component: JournalDashboardGraphField,
    supportedTypes: ["text"],
    extractProps: ({ attrs }) => ({
        graphType: attrs.graph_type,
    }),
};

registerField("dashboard_graph", journalDashboardGraphField);
