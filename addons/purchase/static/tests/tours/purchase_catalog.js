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
        { trigger: "td[data-tooltip='PO/TEST/00002']", run: "click" },
        ...purchaseForm.displayOptionalField("discount"),
        ...purchaseForm.openCatalog(),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 2.50"),
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
        ...productCatalog.goBackToOrder(),
        ...purchaseForm.checkLineValues(0, {
            product: "Crab Juice",
            discount: "10.20",
            quantity: "12.00",
            unit: "Units",
            unitPrice: "2.45",
            totalPrice: "$ 26.40",
        }),

        { trigger: "a[href='/odoo/purchases']", run: "click" },
        { trigger: "td[data-tooltip='PO/TEST/00001']", run: "click" },
        ...purchaseForm.openCatalog(),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 1.55"),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.waitForQuantity("Crab Juice", 1),
        ...productCatalog.checkProductUoM("Crab Juice", "L"),
        ...productCatalog.checkProductPrice("Crab Juice", "$ 1.55"),
        ...productCatalog.goBackToOrder(),
        ...purchaseForm.checkLineValues(0, {
            product: "Crab Juice",
            quantity: "1.00",
            discount: "22.50",
            unit: "L",
            unitPrice: "2.00",
            totalPrice: "$ 1.55",
        }),

        ...purchaseForm.openCatalog(),
        ...productCatalog.addProduct("Crab Juice"),
        ...productCatalog.goBackToOrderViaBreadcrumb(),
        {
            content: "The quantity written just before leaving survives the trip",
            trigger:
                ".o_form_renderer .o_field_x2many tbody tr.o_data_row td[name='product_qty']:contains(2.00)",
        },
    ],
});
