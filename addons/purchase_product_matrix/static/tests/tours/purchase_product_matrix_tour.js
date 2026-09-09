import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

registry.category("web_tour.tours").add("purchase_matrix_tour", {
    url: "/odoo",
    steps: () => [
        stepUtils.showAppsMenuItem(),
        {
            trigger: '.o_app[data-menu-xmlid="purchase.menu_purchase_root"]',
            run: "click",
        },
        {
            trigger: ".o_purchase_order",
        },
        {
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            trigger: ".o_required_modifier[name=partner_id] input",
            run: "edit Agrolait",
        },
        {
            isActive: ["auto"],
            trigger: '.ui-menu-item > a:contains("Agrolait")',
            run: "click",
        },
        {
            trigger: "a:contains('Add a product')",
            run: "click",
        },
        {
            trigger: 'div[name="product_template_id"] input',
            run: "edit Matrix",
        },
        {
            trigger: 'ul.ui-autocomplete a:contains("Matrix")',
            run: "click",
        },
        {
            trigger: ".modal .o_matrix_input_table",
            run: function () {
                [...document.querySelectorAll(".o_matrix_input")].forEach(
                    (el) => (el.value = 1),
                );
            },
        },
        {
            trigger: ".modal .o_matrix_input_table .o_matrix_input:eq(0)",
            run: "edit 0",
        },
        {
            trigger: ".modal .o_matrix_input_table .o_matrix_input:eq(8)",
            run: "edit 0",
        },
        {
            trigger: ".modal button:contains(Confirm)",
            run: "click",
        },
        {
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            trigger: ".o_form_status_indicator_buttons:not(:visible)",
        },
        {
            trigger: ".o_field_pol_product_many2one",
            run: "click",
        },
        {
            trigger: "[name=product_template_id] button.fa-pencil",
            run: "click",
        },
        {
            trigger: ".o_matrix_input_table",
            run: function () {
                [...document.querySelectorAll(".o_matrix_input")]
                    .slice(9, 16)
                    .forEach((el) => (el.value = 4));
            },
        },
        {
            trigger: ".modal button:contains(Confirm)",
            run: "click",
        },
        {
            trigger: '.o_field_cell.o_data_cell.o_list_number:contains("4.00")',
        },
        {
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            trigger: ".o_form_status_indicator_buttons:not(:visible)",
        },
        {
            trigger: 'a:contains("Add a product")',
            run: "click",
        },
        {
            trigger: 'div[name="product_template_id"] input',
            run: "edit Matrix",
        },
        {
            trigger: 'ul.ui-autocomplete a:contains("Matrix")',
            run: "click",
        },
        {
            trigger: 'input[value="4"]',
            run: function () {
                [...document.querySelectorAll("input[value='4']")]
                    .slice(0, 4)
                    .forEach((el) => (el.value = 8.2));
            },
        },
        {
            trigger: ".modal button:contains(Confirm)",
            run: "click",
        },
        {
            trigger: ".o_field_cell.o_data_cell.o_list_number:contains(8.20)",
        },
        ...stepUtils.saveForm(),
    ],
});
