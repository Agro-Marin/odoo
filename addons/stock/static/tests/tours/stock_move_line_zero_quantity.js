import { registry } from "@web/core/registry";

// Moves History colours the quantity by direction: red leaving stock, green
// entering it. A zero is neither, so it must not be painted at all.
registry.category("web_tour.tours").add("test_moves_history_zero_is_neutral", {
    steps: () => [
        {
            content: "Wait for the two move lines to be listed",
            trigger: ".o_list_renderer tr.o_data_row:nth-child(2)",
        },
        {
            content: "The outgoing line that moved something is still red",
            trigger: "tr.o_data_row:has(td[name=product_id]:contains('Alpha Widget'))",
            run() {
                const cell = this.anchor.querySelector("td[name=quantity]");
                if (!cell.classList.contains("text-danger")) {
                    throw new Error(
                        "the fixture is wrong: a non-zero outgoing quantity must stay red",
                    );
                }
            },
        },
        {
            content: "The outgoing line that moved nothing must be neutral",
            trigger: "tr.o_data_row:has(td[name=product_id]:contains('Bravo Widget'))",
            run() {
                const cell = this.anchor.querySelector("td[name=quantity]");
                if (cell.classList.contains("text-danger")) {
                    throw new Error(
                        "a quantity of 0 is painted red, which reads as stock leaving",
                    );
                }
                if (cell.classList.contains("text-success")) {
                    throw new Error("a quantity of 0 is painted green");
                }
            },
        },
    ],
});
