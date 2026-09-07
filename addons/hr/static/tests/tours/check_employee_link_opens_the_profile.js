import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("check_employee_link_opens_the_profile", {
    steps: () => [
        {
            // Following a link to an employee used to refuse an internal user
            // and offer to redirect them to the public employee list. There is
            // one model now: the record opens, and what they read of it is
            // decided field by field.
            trigger: ".o_form_view:contains('Sonic the Hedgehog')",
            content: "The employee profile opens for an internal user",
            timeout: 10000,
        },
    ],
});
