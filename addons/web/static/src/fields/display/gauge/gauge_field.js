// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/gauge/gauge_field - Chart.js doughnut gauge visualization for numeric fields */

import { Component, onWillStart, useEffect, useRef } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Chart, loadChartJS } from "@web/core/lib/chartjs";
import { registerField } from "@web/fields/_registry";
import { formatFloat } from "@web/fields/formatters";
import { standardFieldProps } from "@web/fields/standard_field_props";

/**
 * @typedef {import("@web/fields/standard_field_props").StandardFieldProps & {
 *     maxValueField?: string;
 *     maxValue?: number;
 *     title?: string;
 * }} GaugeFieldProps
 */
/** @extends {Component<GaugeFieldProps>} */
export class GaugeField extends Component {
    static template = "web.GaugeField";
    static props = {
        ...standardFieldProps,
        maxValueField: { type: String, optional: true },
        maxValue: { type: Number, optional: true },
        title: { type: String, optional: true },
    };
    static defaultProps = {
        maxValue: 100,
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
            // Rebuild the (heavyweight) Chart.js instance only when an input
            // that actually changes the gauge changes — not on every render.
            () => {
                const value = this.props.record.data[this.props.name];
                const maxValue = this.props.maxValueField
                    ? this.props.record.data[this.props.maxValueField]
                    : this.props.maxValue;
                return [value, maxValue, this.title];
            },
        );
    }

    /** @returns {string} Chart title from props or the field's string label. */
    get title() {
        return (
            this.props.title || this.props.record.fields[this.props.name].string || ""
        );
    }

    /**
     * @param {number | false} value
     * @returns {string} Human-readable formatted value with 1 decimal.
     */
    formatValue(value) {
        return formatFloat(value, { humanReadable: true, decimals: 1 });
    }

    /** @returns {string} Human-readable formatted value with 1 decimal. */
    get formattedValue() {
        return this.formatValue(this.props.record.data[this.props.name]);
    }

    /** Creates and renders the Chart.js doughnut gauge on the canvas element. */
    renderChart() {
        const gaugeValue = this.props.record.data[this.props.name];
        let maxValue = this.props.maxValueField
            ? this.props.record.data[this.props.maxValueField]
            : this.props.maxValue;
        maxValue = Math.max(gaugeValue, maxValue);
        let maxLabel = maxValue;
        if (gaugeValue === 0 && maxValue === 0) {
            maxValue = 1;
            maxLabel = 0;
        }
        const config = {
            type: "doughnut",
            data: {
                datasets: [
                    {
                        data: [gaugeValue, maxValue - gaugeValue],
                        backgroundColor: ["#1f77b4", "#dddddd"],
                        label: this.title,
                    },
                ],
            },
            options: {
                circumference: 180,
                rotation: 270,
                responsive: true,
                maintainAspectRatio: false,
                cutout: "70%",
                layout: {
                    padding: 5,
                },
                plugins: {
                    title: {
                        display: true,
                        text: this.title,
                        padding: 4,
                    },
                    tooltip: {
                        displayColors: false,
                        callbacks: {
                            label: (tooltipItem) => {
                                if (tooltipItem.dataIndex === 0) {
                                    return _t("Value: %(value)s", {
                                        value: this.formatValue(gaugeValue),
                                    });
                                }
                                return _t("Max: %(max)s", {
                                    max: this.formatValue(maxLabel),
                                });
                            },
                        },
                    },
                },
                aspectRatio: 2,
            },
        };
        this.chart = new Chart(this.canvasRef.el, config);
    }
}

export const gaugeField = {
    component: GaugeField,
    supportedOptions: [
        {
            label: _t("Title"),
            name: "title",
            type: "string",
        },
        {
            label: _t("Max value field"),
            name: "max_field",
            type: "field",
            availableTypes: ["integer", "float"],
        },
        {
            label: _t("Max value"),
            name: "max_value",
            type: "number",
        },
    ],
    extractProps: ({ options }) => ({
        maxValueField: options.max_field,
        maxValue:
            options.max_value === undefined ? undefined : Number(options.max_value),
        title: options.title,
    }),
};

registerField("gauge", gaugeField);
