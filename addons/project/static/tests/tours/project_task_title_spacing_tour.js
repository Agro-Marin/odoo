import { registry } from "@web/core/registry";

/**
 * On a narrow viewport the task title used to share its flex row with the
 * priority/state pair, which cut the title short. This tour asserts the two
 * sit on separate rows.
 */
registry.category("web_tour.tours").add("project_task_title_spacing_tour", {
    url: "/odoo/project",
    steps: () => [
        {
            trigger: ".o_kanban_record:contains(Title Spacing Project)",
            run: "click",
        },
        {
            trigger: ".o_kanban_record:contains(Title Spacing Task)",
            run: "click",
        },
        {
            content: "The title and the priority/state pair are on their own rows",
            trigger: ".o_form_view .o_task_name",
            run() {
                const title = document.querySelector(".o_task_name");
                const widgets = document.querySelector(".o_task_state_widget");
                if (!widgets) {
                    throw new Error("the state widget is not rendered");
                }
                const t = title.getBoundingClientRect();
                const w = widgets.getBoundingClientRect();
                // Two boxes share a flex row exactly when they overlap
                // vertically; centring alone already offsets their tops, so
                // comparing tops proves nothing.
                const overlaps = t.top < w.bottom && w.top < t.bottom;
                if (overlaps) {
                    throw new Error(
                        `at this width the title must not share a row with the ` +
                            `priority/state pair (title ${t.top}-${t.bottom}, ` +
                            `widgets ${w.top}-${w.bottom})`,
                    );
                }
            },
        },
    ],
});
