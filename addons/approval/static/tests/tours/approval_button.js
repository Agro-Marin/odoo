import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("approval_button_tour", {
    steps: () => [
        {
            content: "The gated button shows that it waits for an approval",
            trigger:
                ".o_form_view button[name='action_archive'] .o_approval_button_waiting",
            run: "click",
        },
        {
            content: "Approve from the popover",
            trigger: ".o_approval_button_popover .o_approval_button_approve",
            run: "click",
        },
        {
            content: "The decision is drawn under its step",
            trigger:
                ".o_approval_button_popover .o_approval_button_decision.o_approval_button_approved",
        },
    ],
});
