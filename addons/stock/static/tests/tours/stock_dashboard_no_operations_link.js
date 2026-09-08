import { registry } from "@web/core/registry";

// The Inventory Overview card counted stock.move rows under "Operations", right
// under "Ready", which counts stock.picking rows. Two different numbers with
// labels nobody can tell apart.
registry.category("web_tour.tours").add("test_dashboard_has_no_operations_link", {
    steps: () => [
        {
            content: "Wait for the overview cards",
            trigger: ".o_kanban_renderer .o_kanban_record",
        },
        {
            content: "The card still offers the transfer counts",
            trigger: ".o_kanban_renderer",
            run() {
                if (!this.anchor.querySelector("[name=action_view_pickings_ready]")) {
                    throw new Error(
                        "the fixture is wrong: the Ready link should be on the card",
                    );
                }
            },
        },
        {
            content: "But not the move count that reads the same and means something else",
            trigger: ".o_kanban_renderer",
            run() {
                if (this.anchor.querySelector("[name=action_view_moves_ready]")) {
                    throw new Error(
                        "the dashboard still links to the Operations move list",
                    );
                }
            },
        },
    ],
});
