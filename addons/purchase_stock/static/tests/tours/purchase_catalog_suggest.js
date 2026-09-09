import { productCatalog, purchaseForm } from "@purchase/../tests/tours/tour_helper";
import { assert } from "@stock/../tests/tours/tour_helper";
import { registry } from "@web/core/registry";

import { catalogSuggestion } from "./tour_helper.js";

registry.category("web_tour.tours").add("test_purchase_order_suggest_search_panel_ux", {
    steps: () => [
        { trigger: ".o_purchase_order" },
        ...purchaseForm.createNewPO(),
        ...purchaseForm.selectVendor("Test Vendor"),
        ...purchaseForm.selectWarehouse("Other Warehouse: Receipts"),
        ...purchaseForm.openCatalog(),
        {
            content:
                "Checks suggest is off by default and suggest fields hidden when suggest off",
            trigger: ".o_kanban_view.o_purchase_product_kanban_catalog_view",
            run() {
                const els = document.querySelectorAll(
                    ".o_TimePeriodSelectionField, input.o_PurchaseSuggestInput, .o_purchase_suggest_footer",
                );
                assert(els.length, 0, "Toggle did not hide elements");
            },
        },

        ...productCatalog.addProduct("test_product"),
        ...productCatalog.waitForQuantity("test_product", 1),
        ...productCatalog.goBackToOrder(),
        { trigger: ".o_purchase_order" },
        {
            content: "Confirm PO",
            trigger: 'button[name="action_confirm"]',
            run: "click",
        },
        ...purchaseForm.openCatalog(),
        { trigger: 'body:not(:has(div[name="search_panel_suggestion"]))' },
        ...productCatalog.goBackToOrder(),
        {
            content: "Cancel PO",
            trigger: 'button[name="action_cancel"]',
            run: "click",
        },
        {
            content: "Confirm the cancellation",
            trigger: ".modal-footer button.btn-primary",
            run: "click",
        },
        {
            content: "Reset to draft",
            trigger: 'button[name="action_draft"]',
            run: "click",
        },
        ...purchaseForm.openCatalog(),

        ...catalogSuggestion.toggleSuggest(true),
        {
            content:
                "Toggling Suggestion activates filter for products in PO or suggested",
            trigger: '.o_facet_value:contains("Suggested")',
        },
        ...catalogSuggestion.setParameters({
            basedOn: "Last 3 months",
            nbDays: 90,
            factor: 100,
        }),
        { trigger: "span[name='suggest_total']:visible:contains('$ 20.00')" },
        ...productCatalog.goBackToOrder(),
        ...purchaseForm.selectWarehouse("Inventory Test Company: Receipts"),
        ...purchaseForm.openCatalog(),
        ...catalogSuggestion.setParameters({
            basedOn: "Last 7 days",
            nbDays: 28,
            factor: 50,
        }),
        { trigger: "span[name='suggest_total']:visible:contains('$ 480.00')" },

        ...catalogSuggestion.addAllSuggestions(),
        ...productCatalog.waitForQuantity("test_product", 24),
        ...productCatalog.goBackToOrder(),
        {
            content:
                "Wait for the order line to be re-rendered with the suggested quantity",
            trigger:
                ".o_form_renderer .o_list_view.o_field_x2many tbody tr.o_data_row td[name='product_qty']:contains('24.00')",
        },
        ...purchaseForm.checkLineValues(0, {
            product: "test_product",
            quantity: "24.00",
        }),
        ...purchaseForm.createNewPO(),
        ...purchaseForm.selectVendor("Test Vendor"),
        ...purchaseForm.selectWarehouse("Inventory Test Company: Receipts"),
        ...purchaseForm.openCatalog(),
        ...catalogSuggestion.assertParameters({
            basedOn: "Last 7 days",
            nbDays: 28,
            factor: 50,
        }),
        ...catalogSuggestion.setParameters({
            basedOn: "Last 7 days",
            nbDays: 28,
            factor: 50,
        }),
        { trigger: "span[name='suggest_total']:visible:contains('480')" },
        ...catalogSuggestion.assertCatalogRecord("test_product", {
            monthly: 52,
            suggest: 24,
            forecast: 100,
        }),
        ...catalogSuggestion.checkKanbanRecordPosition("test_product", 0),

        ...catalogSuggestion.setParameters({
            basedOn: "Last 30 days",
            factor: 10,
        }),
        { trigger: "span[name='suggest_total']:visible:contains('60')" },
        ...catalogSuggestion.assertCatalogRecord("test_product", {
            monthly: 24,
            suggest: 3,
        }),

        ...catalogSuggestion.setParameters({
            basedOn: "Last 3 months",
            factor: 500,
        }),
        { trigger: "span[name='suggest_total']:visible:contains('740')" },
        ...catalogSuggestion.assertCatalogRecord("test_product", {
            monthly: 8,
            suggest: 37,
        }),

        ...catalogSuggestion.setParameters({
            basedOn: "Forecasted",
            nbDays: 18,
            factor: 100,
        }),
        { trigger: "span[name='suggest_total']:visible:contains('1,000')" },
        ...catalogSuggestion.assertCatalogRecord("test_product", {
            forecast: 50,
            suggest: 50,
        }),

        ...catalogSuggestion.setParameters({ nbDays: 7 }),
        { trigger: "span[name='suggest_total']:visible:contains('$ 0.00')" },
        { trigger: ".o_view_nocontent_smiling_face" },

        ...catalogSuggestion.toggleSuggest(false),
        ...catalogSuggestion.assertCatalogRecord("test_product", {
            forecast: 100,
            monthly: 24,
        }),
        ...catalogSuggestion.checkKanbanRecordPosition("Other product", 0),
        {
            trigger: "span[name='kanban_monthly_demand_qty']:visible:contains('24')",
        },

        ...productCatalog.addProduct("Other product"),
        ...productCatalog.waitForQuantity("Other product", 1),
        ...catalogSuggestion.toggleSuggest(true),

        ...catalogSuggestion.removeSuggestFilter(),
        ...catalogSuggestion.toggleSuggest(false),
        ...catalogSuggestion.checkKanbanRecordPosition("Other product", 0),

        ...productCatalog.goBackToOrder(),
        ...purchaseForm.openCatalog(),
        ...catalogSuggestion.toggleSuggest(true),
        ...catalogSuggestion.checkKanbanRecordPosition("Other product", 1),

        ...productCatalog.selectSearchPanelCategory("Goods"),
        { trigger: "span[name='suggest_total']:visible:contains('$ 0.00')" },
        ...productCatalog.selectSearchPanelCategory("Test Category"),
        { trigger: "span[name='suggest_total']:visible:contains('$ 480.00')" },
        ...catalogSuggestion.removeSuggestFilter(),
        { trigger: "span[name='suggest_total']:visible:contains('$ 480.00')" },

        ...productCatalog.goBackToOrder(),
        {
            content: "Go back to the dashboard",
            trigger: ".o_menu_brand",
            run: "click",
        },
    ],
});
