import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("mail_activity_schedule_from_chatter", {
    steps: () => [
        {
            trigger: "button:contains('Activity')",
            run: "click",
        },
        {
            trigger: ".o_selection_badge span:contains('Call')",
            run: "click",
        },
        {
            trigger: ".o_selection_badge.active span:contains('Call')",
        },
        {
            trigger: ".o_selection_badge span:contains('To-Do')",
            run: "click",
        },
        {
            // The assignee picker must not offer to create a user: a stray
            // click there onboards (and bills) a real one.
            trigger: "div[name='activity_user_id'] input",
            run: "edit Nobody Here",
        },
        {
            // Wait for the dropdown to have rendered its suggestions: they are
            // all built in one pass, so once there is an item the set is final.
            trigger: ".o-autocomplete--dropdown-menu li",
            async run() {
                // The suggestions do not all land in the same tick, so settle
                // before asserting an absence -- otherwise this passes by
                // simply looking too early.
                await new Promise((resolve) => setTimeout(resolve, 1000));
                const create = document.querySelector(
                    ".o-autocomplete--dropdown-menu .o_m2o_dropdown_option_create"
                );
                if (create) {
                    throw new Error(
                        `the assignee picker still offers to create a user: "${create.textContent.trim()}"`
                    );
                }
            },
        },
        {
            trigger: "div[name='activity_user_id'] input",
            run: "clear",
        },
        {
            trigger: "div[name='summary'] input",
            run: "edit Play Mario Party",
        },
        {
            trigger: "button:contains('Save')",
            run: "click",
        },
        {
            trigger: ".o-mail-Activity:contains('Play Mario Party')",
            run: "click",
        },
        {
            trigger: "button:contains('Activity')",
            run: "click",
        },
        {
            trigger: "div[name='summary'] input",
            run: "edit Play Mario Kart",
        },
        {
            trigger: "button.btn.btn-secondary:contains('Mark Done')",
            run: "click",
        },
        {
            trigger: ".o-mail-Message:contains('Play Mario Kart')",
        },
    ],
});
