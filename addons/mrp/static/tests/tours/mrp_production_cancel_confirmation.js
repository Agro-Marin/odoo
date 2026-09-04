import { registry } from "@web/core/registry";

// Cancelling a manufacturing order cannot be undone: `_compute_state` keeps
// `cancel` for good and no view offers a way back to draft. Both confirmation
// dialogs must say which action they are about to run, and must not offer a
// plain "Cancel" as the way to back out of cancelling.
//
// The dialog title stays the generic one: `common.rng` has no `confirm-title`
// attribute on `<button>`, so no view in this tree can set it.

registry.category("web_tour.tours").add("test_mrp_production_cancel_confirmation_form", {
    steps: () => [
        {
            content: "Ask to cancel the manufacturing order",
            trigger: ".o_form_view button[name=action_cancel]",
            run: "click",
        },
        {
            content: "The dialog warns that the order cannot be brought back",
            trigger: ".modal .modal-body:contains(This action cannot be undone.)",
        },
        {
            content: "Confirming reads as the action, not as 'Confirm'",
            trigger: ".modal footer button.btn-primary:contains(Cancel this Order)",
        },
        {
            content: "Backing out reads as 'Discard', never as another 'Cancel'",
            trigger: ".modal footer button.btn-secondary:contains(Discard)",
            run: "click",
        },
        {
            content: "The order is still there",
            trigger: ".o_form_view:not(:has(.modal)) button[name=action_cancel]",
        },
    ],
});

registry.category("web_tour.tours").add("test_mrp_production_cancel_confirmation_list", {
    steps: () => [
        {
            content: "Select a manufacturing order",
            trigger: ".o_list_renderer .o_data_row:first .o_list_record_selector input",
            run: "click",
        },
        {
            content: "Ask to cancel the selection",
            trigger: ".o_control_panel_actions button[name=action_cancel]",
            run: "click",
        },
        {
            content: "The dialog warns that the orders cannot be brought back",
            trigger: ".modal .modal-body:contains(This action cannot be undone.)",
        },
        {
            content: "Confirming reads as the action, not as 'Ok'",
            trigger: ".modal footer button.btn-primary:contains(Cancel these Orders)",
        },
        {
            content: "Backing out reads as 'Discard', never as another 'Cancel'",
            trigger: ".modal footer button.btn-secondary:contains(Discard)",
            run: "click",
        },
        {
            content: "The orders are still there",
            trigger: ".o_list_renderer .o_data_row:not(:has(.modal))",
        },
    ],
});
