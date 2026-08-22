// @ts-check
/** @odoo-module native */

import { getColor, getCustomColor, hexToRGBA } from "@web/core/colors/colors";
import { Chart } from "@web/core/lib/chartjs";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { useChartCanvas } from "@web/fields/chart_canvas_hook";
import { FieldComponent } from "@web/fields/field_component";
import { archAttribute } from "@web/fields/field_options";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class JournalDashboardGraphField extends FieldComponent {
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
        graphType: "bar",
    };

    setup() {
        this.canvasRef = useChartCanvas(() => [this.field.value]);
    }

    renderChart() {
        if (this.chart) {
            this.chart.destroy();
        }
        try {
            this.data = JSON.parse(this.field.value || "[]");
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
    /** @returns {Object} */
    getLineChartConfig() {
        const labels = this.data[0].values.map((pt) => pt.x);
        const color10 = getColor(3, "odoo");
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

        const gridColor = getCustomColor("#d8dadd", "#3C3E4B");
        const labelColor = getCustomColor("#111827", "#E4E4E4");
        const color13 = getColor(2, "odoo");
        const color19 = getColor(1, "odoo");
        this.data[0].values.forEach((pt) => {
            data.push(pt.value);
            labels.push(pt.label);
            if (pt.type === "past") {
                backgroundColor.push(color13);
            } else if (pt.type === "future") {
                backgroundColor.push(color19);
            } else {
                backgroundColor.push(getCustomColor("#ebebeb", "#3C3E4B"));
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

/** @type {import("registries").FieldsRegistryItemShape} */
const journalDashboardGraphField = {
    component: JournalDashboardGraphField,
    supportedAttributes: [
        archAttribute("graph_type", _t("Graph type"), {
            type: "selection",
            help: _t("`bar` or `line`."),
        }),
    ],
    supportedTypes: ["text"],
    extractProps: ({ attrs }) => ({
        graphType: attrs.graph_type,
    }),
};

registerField("dashboard_graph", journalDashboardGraphField);
