import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("approvals_tour", {
    url: "/odoo/action-approval.action_approval_category_dashboard",
    steps: () => [
        {
            trigger: 'button[name="create_request"]:first',
            content: "create new request",
            run: "click",
        },
        {
            trigger: '.o_field_widget[name="date_start"] input',
            content: "give start date",
            run: "edit 12/13/2018 13:00:00",
        },
        {
            trigger: '.o_field_widget[name="date_end"] input',
            content: "give end date",
            run: "edit 12/20/2018 13:00:00",
        },
        {
            trigger: '.o_field_widget[name="location"] input',
            content: "give location",
            run: "edit Berlin, Schulz Hotel",
        },
        {
            trigger: 'div[name="reason"] .odoo-editor-editable',
            content: "give description",
            run: "editor (We need to go, because reason (and also for beer)))",
        },
        {
            trigger: ".o_form_button_save",
            content: "save the request",
            run: "click",
        },
        {
            trigger: 'a:contains("Approver(s)"):first',
            content: "open approvers page to verify approvers",
            run: "click",
        },
        {
            trigger: '.o_field_widget[name="approver_ids"] .o_data_row',
            content: "verify approver is present (auto-populated from category)",
        },
        {
            trigger: "button[name=action_confirm]:enabled",
            content: "confirm the request",
            run: "click",
        },
        {
            trigger: 'button[name="action_approve"]:enabled',
            content: "approve the request",
            run: "click",
        },
        {
            trigger: 'button[aria-checked="true"][data-value="approved"]',
            content: "wait until the request status flips to approved",
        },
        {
            trigger: 'button[name="action_withdraw"]:enabled',
            content: "withdraw the approval to return to pending",
            run: "click",
        },
        {
            trigger: 'button[name="action_cancel"]:enabled',
            content: "cancel request",
            run: "click",
        },
        {
            trigger: ".modal-footer button.btn-primary",
            content: "confirm cancellation in the dialog",
            run: "click",
        },
        {
            trigger: 'button[aria-checked="true"][data-value="cancelled"]',
            content: "wait until the request status flips to cancelled",
        },
    ],
});
