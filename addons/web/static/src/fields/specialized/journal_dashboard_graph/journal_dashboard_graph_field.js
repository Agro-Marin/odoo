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
    static props = {
        ...standardFieldProps,
        graphType: String,
    };

    setup() {
        this.chart = null;
        this.canvasRef = useRef("canvas");

        onWillStart(async () => {
            await loadChartJS();
        });

        // Rebuild only when the serialized graph data actually changes — not on
        // every render. Parsing happens inside renderChart so the chart reflects
        // the current field value (it was parsed once in setup and went stale).
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
        this.data = JSON.parse(this.props.record.data[this.props.name] || "[]");
        if (!this.data.length) {
            return;
        }
        let config;
        if (this.props.graphType === "line") {
            config = this.getLineChartConfig();
        } else if (this.props.graphType === "bar") {
            config = this.getBarChartConfig();
        }
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

        // Read the color scheme fresh per render (not once at module load) so a
        // light/dark toggle without a hard reload re-themes the grid/labels too,
        // matching the line chart which already reads the cookie per render.
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
