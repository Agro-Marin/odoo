import { registry } from "@web/core/registry";

// `date_planned` defaults to now on a record that does not exist yet, so the
// "this is late" decorations turn on as soon as a second has passed and the
// form re-renders. A transfer nobody has saved cannot be late.
registry.category("web_tour.tours").add("test_new_picking_is_never_late", {
    steps: () => [
        {
            content: "Start a new transfer",
            trigger: ".o_control_panel button.o_form_button_create, .o_list_button_add",
            run: "click",
        },
        {
            content: "Wait for the scheduled date to be laid out",
            trigger: ".o_form_view div[name=date_planned]",
        },
        {
            content: "Let the clock pass the default scheduled date",
            trigger: ".o_form_view div[name=date_planned]",
            async run() {
                await new Promise((resolve) => setTimeout(resolve, 1500));
            },
        },
        {
            content: "Touch another field so the form re-renders against the new now",
            trigger: ".o_form_view div[name=partner_id] input",
            run: "edit Anything",
        },
        {
            content: "The scheduled date of an unsaved transfer must not read as late",
            trigger: ".o_form_view div[name=date_planned]",
            run() {
                const field = this.anchor;
                if (field.querySelector(".text-warning") || field.classList.contains("text-warning")) {
                    throw new Error(
                        "a transfer that has never been saved is painted as overdue",
                    );
                }
                if (field.querySelector(".fw-bold") || field.classList.contains("fw-bold")) {
                    throw new Error(
                        "a transfer that has never been saved is emphasised as overdue",
                    );
                }
            },
        },
        {
            content: "Leave no dirty form behind",
            trigger: ".o_form_button_cancel",
            run: "click",
        },
    ],
});

// The control: guarding the decorations on `id` must not switch them off for
// the records they were written for.
registry.category("web_tour.tours").add("test_saved_late_picking_is_marked", {
    steps: () => [
        {
            content: "Wait for the saved late transfer to be laid out",
            trigger: ".o_form_view div[name=date_planned]",
        },
        {
            content: "A saved transfer past its scheduled date still reads as late",
            trigger: ".o_form_view div[name=date_planned]",
            run() {
                const field = this.anchor;
                const isWarning =
                    field.querySelector(".text-warning") ||
                    field.classList.contains("text-warning");
                if (!isWarning) {
                    throw new Error(
                        "an overdue transfer lost its warning decoration",
                    );
                }
            },
        },
    ],
});
