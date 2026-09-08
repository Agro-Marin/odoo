import { registry } from "@web/core/registry";

// The Lots/Serials list opened on "Created on" and hid the quantity, so the
// column that answers "how much of this lot is left" had to be switched on by
// hand on every fresh session.
registry.category("web_tour.tours").add("test_lot_list_default_columns", {
    steps: () => [
        {
            content: "Wait for the lots list to be laid out",
            trigger: ".o_list_renderer th[data-name=name]",
        },
        {
            content: "On Hand Quantity is one of the columns you get",
            trigger: ".o_list_renderer thead",
            run() {
                if (!this.anchor.querySelector("th[data-name=product_qty]")) {
                    throw new Error(
                        "the quantity of the lot is hidden behind the optional-columns menu",
                    );
                }
            },
        },
        {
            content: "Created on is not",
            trigger: ".o_list_renderer thead",
            run() {
                if (this.anchor.querySelector("th[data-name=create_date]")) {
                    throw new Error(
                        "the lots list still spends a column on the creation date",
                    );
                }
            },
        },
    ],
});
