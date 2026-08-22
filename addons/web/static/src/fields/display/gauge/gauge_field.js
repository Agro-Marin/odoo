// @ts-check
/** @odoo-module native */

import { formatFieldFloat } from "@web/core/formatters";
import { Chart } from "@web/core/lib/chartjs";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { useChartCanvas } from "@web/fields/chart_canvas_hook";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

/**
 * @typedef {import("@web/fields/standard_field_props").StandardFieldProps & {
 * maxValueField?: string;
 * maxValue?: number;
 * title?: string;
 * }} GaugeFieldProps
 */
/** @extends {FieldComponent<GaugeFieldProps>} */
export class GaugeField extends FieldComponent {
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

    /** @type {import("@odoo/owl").Ref} */
    canvasRef;

    setup() {
        this.canvasRef = useChartCanvas(() => [
            this.field.value,
            this.props.maxValueField
                ? this.props.record.data[this.props.maxValueField]
                : this.props.maxValue,
            this.title,
        ]);
    }

    /** @returns {string} */
    get title() {
        return this.props.title || this.field.definition.string || "";
    }

    /**
     * @param {number | false} value
     * @returns {string}
     */
    formatValue(value) {
        return formatFieldFloat(value, { humanReadable: true, decimals: 1 });
    }

    /** @returns {string} */
    get formattedValue() {
        return this.formatValue(
            /** @type {Record<string, any>} */ (this.props.record.data)[
                this.props.name
            ],
        );
    }

    /**
     * @returns {number}
     */
    get configuredMaxValue() {
        const raw = this.props.maxValueField
            ? /** @type {Record<string, any>} */ (this.props.record.data)[
                  this.props.maxValueField
              ]
            : this.props.maxValue;
        return typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
    }

    renderChart() {
        const rawValue = /** @type {Record<string, any>} */ (this.props.record.data)[
            this.props.name
        ];
        const gaugeValue =
            typeof rawValue === "number" && Number.isFinite(rawValue) ? rawValue : 0;
        const configuredMax = this.configuredMaxValue;
        let maxValue = Math.max(gaugeValue, configuredMax);
        let maxLabel = configuredMax;
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
                            label: (/** @type {any} */ tooltipItem) => {
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

/** @type {import("registries").FieldsRegistryItemShape} */
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
    supportedTypes: ["integer", "float"],
    fieldDependencies: ({ options }) =>
        options.max_field
            ? [{ name: options.max_field, type: "float", readonly: true }]
            : [],
    extractProps: ({ options }) => ({
        maxValueField: options.max_field,
        maxValue:
            options.max_value === undefined ? undefined : Number(options.max_value),
        title: options.title,
    }),
};

registerField("gauge", gaugeField);
