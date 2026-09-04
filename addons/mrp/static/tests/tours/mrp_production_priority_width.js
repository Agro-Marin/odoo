import { registry } from "@web/core/registry";

// The priority column paints a single star, but `priority` is a selection
// field and the list layout has no width for that widget, so it falls back to
// the generic 80px minimum. Guard the arch attribute that pins it to one glyph.
const MAX_STAR_COLUMN_WIDTH = 60;

registry.category("web_tour.tours").add("test_mrp_production_priority_column_width", {
    steps: () => [
        {
            content: "Wait for the manufacturing orders list to be laid out",
            trigger: ".o_list_renderer th[data-name=priority][style*='width']",
        },
        {
            content: "The priority column must be star-sized, not selection-sized",
            trigger: ".o_list_renderer th[data-name=priority]",
            run() {
                const width = this.anchor.getBoundingClientRect().width;
                if (width > MAX_STAR_COLUMN_WIDTH) {
                    throw new Error(
                        `The priority column is ${Math.round(width)}px wide; ` +
                            "expected a single star (20px plus cell padding).",
                    );
                }
            },
        },
    ],
});
