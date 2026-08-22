import { addSectionFromProductCatalog } from "@account/js/tours/tour_utils";
import { registry } from "@web/core/registry";

import { productCatalog, purchaseForm } from "./tour_helper.js";

registry
    .category("web_tour.tours")
    .add("test_add_section_from_product_catalog_on_purchase_order", {
        steps: () => [
            ...purchaseForm.createNewPO(),
            ...purchaseForm.selectVendor("Test Vendor"),
            ...addSectionFromProductCatalog(),
        ],
    });

registry.category("web_tour.tours").add("test_catalog_vendor_uom", {
    steps: () => [
        // Open the PO for the vendor selling product as "Units".
        { trigger: "td[data-tooltip='PO/TEST/00002']", run: "click" },
        ...purchaseForm.displayOptionalField("discount"),
        ...purchaseForm.openCatalog(),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 2.50"),
        // Add 6 units and check the price is correctly updated.
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.checkProductUoM("Crab Juice", "Units"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.waitForQuantity("Crab Juice", 5),
        ...productCatalog.checkProductUoM("Crab Juice", "Units"),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 2.50"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 2.45"),
        // Add 6 units more and check the price is updated again.
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.waitForQuantity("Crab Juice", 11),
        ...productCatalog.checkProductUoM("Crab Juice", "Units"),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 2.45"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 2.20"),
        // Go back in the PO form view and check PO line price and qty is correct.
        ...productCatalog.goBackToOrder(),
        ...purchaseForm.checkLineValues(0, {
            product: "Crab Juice",
            discount: "10.20",
            quantity: "12.00",
            unit: "Units",
            unitPrice: "2.45",
            totalPrice: "$ 26.40",
        }),

        // Open the PO for the vendor selling product as liter.
        { trigger: "a[href='/odoo/purchases']", run: "click" },
        { trigger: "td[data-tooltip='PO/TEST/00001']", run: "click" },
        ...purchaseForm.openCatalog(),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 1.55"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.waitForQuantity("Crab Juice", 1),
        ...productCatalog.checkProductUoM("Crab Juice", "L"),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 1.55"),
        // Go back in the PO form view and check PO line price and qty is correct.
        ...productCatalog.goBackToOrder(),
        ...purchaseForm.checkLineValues(0, {
            product: "Crab Juice",
            quantity: "1.00",
            discount: "22.50",
            unit: "L",
            unitPrice: "2.00",
            totalPrice: "$ 1.55",
        }),

        // Same race, the other exit: bump the quantity and leave immediately
        // through the breadcrumb instead of the button. The card's write is
        // debounced 500ms, so the order form must still show 2.00 -- it is the
        // action service, not the catalog's own handler, that has to wait.
        ...purchaseForm.openCatalog(),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.goBackToOrderViaBreadcrumb(),
        {
            // A waiting trigger, not an immediate read: the restored form
            // renders its cached record before its reload returns, so the value
            // arrives a beat later. What must never happen is that it stays at
            // 1.00 -- that is the write being lost, which is what this guards.
            content: "The quantity written just before leaving survives the trip",
            trigger:
                ".o_form_renderer .o_field_x2many tbody tr.o_data_row td[name='product_qty']:contains(2.00)",
        },
    ],
});
