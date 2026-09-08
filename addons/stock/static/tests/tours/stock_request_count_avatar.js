import { registry } from "@web/core/registry";

// Every other user field in Inventory is drawn with its avatar. The Request a
// Count dialog was the one that was not, so the responsible was a bare name.
registry.category("web_tour.tours").add("test_request_count_shows_avatar", {
    steps: () => [
        {
            content: "Select the quant to count",
            trigger: ".o_data_row .o_list_record_selector input",
            run: "click",
        },
        {
            content: "Ask for a count",
            trigger: ".o_control_panel button:contains('Request a Count')",
            run: "click",
        },
        {
            content: "Name a responsible",
            trigger: ".modal div[name=user_id] input",
            run: "edit Mitchell",
        },
        {
            trigger: ".ui-autocomplete .ui-menu-item a:contains('Mitchell')",
            run: "click",
        },
        {
            content: "The responsible must be drawn with an avatar, not as a bare name",
            trigger: ".modal div[name=user_id]",
            run() {
                if (!this.anchor.querySelector("img")) {
                    throw new Error(
                        "the Assign to field draws no avatar; the responsible is a bare name",
                    );
                }
            },
        },
        {
            content: "Leave the dialog clean behind us",
            trigger: ".modal footer button:contains('Discard')",
            run: "click",
        },
        {
            trigger: "body:not(:has(.modal))",
        },
    ],
});
