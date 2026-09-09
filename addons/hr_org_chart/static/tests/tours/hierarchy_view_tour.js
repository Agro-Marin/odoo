import { registry } from "@web/core/registry";

/**
 * The hierarchy view has HOOT coverage but, until this tour, nothing drove it
 * against a real server: every one of its reads -- `hierarchy_read`, the
 * `web_search_read` behind an unfold, the aggregate that counts the children --
 * was answered by a mock. A mock that drifts from the server is the failure
 * this covers, and the shape it took once already: the client sent the view's
 * order to `formatted_read_group`, which refuses an order term that is neither
 * a groupby nor an aggregate, and every unfold raised against a real database
 * while the suite stayed green.
 */
const card = (name) =>
    `.o_hierarchy_node_container:has(.o_hierarchy_node_content:contains('${name}'))`;

registry.category("web_tour.tours").add("hierarchy_view_tour", {
    steps: () => [
        {
            content: "Switch to the hierarchy view",
            trigger: "button.o_switch_view.o_hierarchy",
            run: "click",
        },
        {
            content: "The roots are drawn, and only the roots",
            trigger: `.o_hierarchy_view ${card("Hierarchy Root")}`,
        },
        {
            content: "Unfold the root: its reports are read from the server",
            trigger: `${card("Hierarchy Root")} .o_hierarchy_node_button.btn-primary`,
            run: "click",
        },
        {
            content: "Both reports are drawn",
            trigger: card("Hierarchy Report A"),
        },
        {
            content: "...and so is the second one",
            trigger: card("Hierarchy Report B"),
        },
        {
            content: "Unfold the report that has one of its own",
            trigger: `${card("Hierarchy Report A")} .o_hierarchy_node_button.btn-primary`,
            run: "click",
        },
        {
            content: "The third level is drawn",
            trigger: card("Hierarchy Grandchild"),
        },
        {
            content: "Fold the root again",
            trigger: `${card("Hierarchy Root")} .o_hierarchy_node_button.btn-secondary`,
            run: "click",
        },
        {
            content: "The branch is gone and the root offers to unfold once more",
            trigger: `${card("Hierarchy Root")} .o_hierarchy_node_button.btn-primary`,
        },
    ],
});
