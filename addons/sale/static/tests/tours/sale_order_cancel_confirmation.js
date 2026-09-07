import { registry } from "@web/core/registry";

/**
 * The button that cancels the order says "Cancel" and so does the button that
 * dismisses its own confirmation dialog. This tour pins the wording that tells
 * them apart, through the real view arch and the real view-button hook.
 */
registry.category("web_tour.tours").add("sale_order_cancel_confirmation", {
    steps: () => [
        {
            content: "ask to cancel the order",
            trigger: "button[name=action_cancel]",
            run: "click",
        },
        {
            content: "the dialog names the action instead of saying 'Confirmation'",
            trigger: ".modal .modal-title:contains('Cancel Order')",
        },
        {
            content: "the way out is 'No, go back', not a second 'Cancel'",
            trigger: ".modal footer button.btn-secondary:contains('No, go back')",
        },
        {
            content: "the confirm button carries the verb, not 'Ok'",
            trigger: ".modal footer button.btn-primary:contains('Yes, cancel order')",
            run: "click",
        },
        {
            content: "the order is cancelled, so it offers to go back to a quotation",
            trigger: "button[name=action_draft]",
        },
    ],
});
