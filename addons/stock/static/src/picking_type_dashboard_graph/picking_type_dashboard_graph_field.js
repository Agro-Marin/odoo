/** @odoo-module native */
import { cookie } from "@web/core/browser/cookie";
import { getColor, getCustomColor } from "@web/core/colors/colors";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { JournalDashboardGraphField } from "@web/fields/specialized/journal_dashboard_graph/journal_dashboard_graph_field";

export class PickingTypeDashboardGraphField extends JournalDashboardGraphField {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }
    getBarChartConfig() {
        // Only bar chart is available for picking types
        const data = [];
        const labels = [];
        const backgroundColor = [];

        const colorPast = getColor(8, cookie.get("color_scheme"));
        const colorPresent = getColor(16, cookie.get("color_scheme"));
        const colorFuture = getColor(12, cookie.get("color_scheme"));
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
                backgroundColor.push(getCustomColor(cookie.get("color_scheme"), "#ebebeb", "#3C3E4B"));
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
                    // Sample data has no picking type id and is not clickable.
                    // `elements` is empty when the click misses every bar.
                    const pickingTypeId = this.data[0].picking_type_id;
                    if (!pickingTypeId || !elements.length) {
                        return;
                    }
                    const columnIndex = elements[0].index;
                    // Prefer the server-provided category slug on the clicked bar;
                    // fall back to the positional map only for older cached graph
                    // data that predates the `category` key.
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
                    // Add a filter for the given date category
                    additionalContext["search_default_".concat(dateCategory)] = true;
                    this.actionService.doAction("stock.click_dashboard_graph", {
                        additionalContext: additionalContext
                    });
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        // Suppress the tooltip over fake sample bars (matches the
                        // parent JournalDashboardGraphField behaviour).
                        enabled: !this.data[0]?.is_sample_data,
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

registry.category("fields").add("picking_type_dashboard_graph", pickingTypeDashboardGraphField);
