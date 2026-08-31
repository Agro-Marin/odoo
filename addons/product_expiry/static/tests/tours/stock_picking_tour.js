import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("test_generate_serial_with_expiration", {
    steps: () => [
        {
            trigger: "button:contains('Details')",
            run: "click",
        },
        {
            trigger: ".o_widget_generate_serials > button",
            run: "click",
        },
        {
            trigger: ".modal .btn-primary:contains('New')",
            run: "click",
        },
        {
            trigger: ".modal .btn-primary:contains('Generate')",
            run: "click",
        },
        // Check that the expiration date is now set after generating Serials/Lots.
        {
            trigger: "td.o_field_cell[name=expiration_date]",
            run: () => {
                const exp_dates = document.querySelectorAll(
                    "td.o_field_cell[name=expiration_date]",
                );
                for (const exp_date of exp_dates) {
                    if (exp_date.innerText.trim() !== "Jun 3, 2020, 12:00 AM") {
                        throw new Error("Expiration date should be Jun 3, 12:00 AM.");
                    }
                }
            },
        },
        {
            trigger: ".modal button:contains(save)",
            run: "click",
        },
        // Saving the detailed-operations dialog persists the picking, so the
        // form's own save button is already hidden by `.invisible` here. The
        // tour used to click it and waited out the timeout on an element that
        // cannot become visible; assert the saved state instead.
        {
            trigger: ".o_form_saved",
        },
        {
            trigger: "body",
            run: () => {
                if (document.querySelector(".o_form_dirty")) {
                    throw new Error(
                        "the record is still dirty after the dialog was saved",
                    );
                }
            },
        },
    ],
});
