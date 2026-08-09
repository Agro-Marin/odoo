import { addSectionFromProductCatalog } from "@account/js/tours/tour_utils";
import { registry } from "@web/core/registry";

/**
 * Name of the customer both catalog tours select. The tests create it, so the
 * tours never depend on which partners happen to exist.
 */
export const CATALOG_TOUR_CUSTOMER = "Catalog Tour Customer";

/**
 * Steps creating a new sale order for a *named* customer.
 *
 * These steps used to open the customer dropdown without typing and click
 * ``.dropdown-item:first``, which made them depend on the ambient partner set
 * and on the dropdown's ordering: with no demo data — this fork's default,
 * ``--without-demo`` (odoo/tools/config.py) — the first entry is not a
 * selectable partner, the customer stayed empty, and the order was too
 * invalid to open the catalog at all. Every later step then failed against a
 * form that had never left its initial state.
 *
 * Typing the name first narrows the dropdown to one known record, so the tour
 * asserts what it means to and passes with or without demo data.
 */
function createSaleOrderForCustomer() {
    return [
        {
            content: "Create a new SO",
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            content: "Type the customer name",
            trigger: ".o_field_res_partner_many2one input.o_input",
            run: `edit ${CATALOG_TOUR_CUSTOMER}`,
        },
        {
            content: "Wait for the field to be active",
            trigger: ".o_field_res_partner_many2one input[aria-expanded=true]",
        },
        {
            content: "Select that customer from the dropdown",
            trigger: `.o_field_res_partner_many2one .dropdown-item:not([id$='_loading']):contains("${CATALOG_TOUR_CUSTOMER}")`,
            run: "click",
        },
        {
            content: "Wait for the customer to be set",
            trigger: ".o_field_res_partner_many2one input[aria-expanded=false]",
        },
    ];
}

registry.category("web_tour.tours").add("sale_catalog", {
    steps: () => [
        ...createSaleOrderForCustomer(),
        {
            content: "Open product catalog",
            trigger: 'button[name="action_add_from_catalog"]',
            run: "click",
        },
        {
            content: "Type 'Restricted' into the search bar",
            trigger: "input.o_searchview_input",
            run: "edit Restricted",
        },
        {
            content: "Search for the product",
            trigger: "input.o_searchview_input",
            run: "press Enter",
        },
        {
            content: "Wait for catalog rendering",
            trigger: '.o_kanban_record:contains("Restricted Product")',
        },
        {
            content: "Wait for filtering",
            trigger:
                '.o_kanban_renderer:not(:has(.o_kanban_record:contains("AAA Product")))',
        },
        {
            content: "Add the product to the SO",
            trigger:
                '.o_kanban_record:contains("Restricted Product") .fa-shopping-cart',
            run: "click",
        },
        {
            content: "Wait for product to be added",
            trigger:
                '.o_kanban_record:contains("Restricted Product"):not(:has(.fa-shopping-cart))',
        },
        {
            content: "Input a custom quantity",
            trigger: '.o_kanban_record:contains("Restricted Product") .o_input',
            run: "edit 6",
        },
        {
            content: "Increase the quantity",
            trigger: '.o_kanban_record:contains("Restricted Product") .fa-plus',
            run: "click",
        },
        {
            content: "Close the catalog",
            trigger: ".o-kanban-button-back",
            run: "click",
        },
    ],
});

registry
    .category("web_tour.tours")
    .add("test_add_section_from_product_catalog_on_sale_order", {
        steps: () => [
            ...createSaleOrderForCustomer(),
            ...addSectionFromProductCatalog(),
        ],
    });
