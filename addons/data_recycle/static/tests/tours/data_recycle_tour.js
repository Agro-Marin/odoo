import { registry } from "@web/core/registry";

/**
 * The queue list runs a `js_class` controller whose Validate button reaches into
 * `model.root`. Grouping swaps that root from a DynamicRecordList to a
 * DynamicGroupList, so the flow is exercised grouped -- the search view offers a
 * Group By on purpose and nothing else covers that combination.
 */
registry.category("web_tour.tours").add("data_recycle_validate_grouped", {
    url: "/odoo/field-recycle",
    steps: () => [
        {
            content: "the queue is there",
            trigger: ".o_data_recycle_list_view, .o_list_view",
        },
        {
            content: "open the search dropdown",
            trigger: ".o_searchview_dropdown_toggler",
            run: "click",
        },
        {
            content: "group the queue by model",
            trigger: ".o_group_by_menu .o_menu_item:contains(Model)",
            run: "click",
        },
        {
            content: "the list is grouped",
            trigger: ".o_group_header",
        },
        {
            content: "open the first group",
            trigger: ".o_group_header:first",
            run: "click",
        },
        {
            content: "select every record in the group",
            trigger: "thead .o_list_record_selector input",
            run: "click",
        },
        {
            content: "the Validate button appears on a grouped selection",
            trigger: ".o_data_recycle_validate_button",
            run: "click",
        },
        {
            content: "the queue shrank and no error dialog appeared",
            trigger: ".o_list_view:not(:has(.o_data_recycle_validate_button))",
        },
        {
            trigger: "body:not(:has(.o_error_dialog)):not(:has(.o_dialog))",
        },
    ],
});

/**
 * The "selects every record" alert is an `invisible=` expression comparing the
 * `domain` Char to the literal the domain widget writes for "no filter". That
 * string comparison is only ever exercised in a rendered form.
 */
registry.category("web_tour.tours").add("data_recycle_unfiltered_warning", {
    steps: () => [
        {
            content: "the rule with no filter warns that it selects everything",
            trigger: ".o_form_view .alert-warning:contains(selects every record)",
        },
    ],
});

registry.category("web_tour.tours").add("data_recycle_filtered_no_warning", {
    steps: () => [
        {
            content: "the form is loaded and showing the filter",
            trigger: ".o_form_view .o_field_widget[name=domain]",
        },
        {
            content: "a rule that has a filter carries no warning",
            trigger: ".o_form_view:not(:has(.alert-warning))",
        },
    ],
});
