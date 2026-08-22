import comboConfiguratorTourUtils from "@sale/js/tours/combo_configurator_tour_utils";
import productConfiguratorTourUtils from "@sale/js/tours/product_configurator_tour_utils";
import tourUtils from "@sale/js/tours/tour_utils";
import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

registry.category("web_tour.tours").add("sale_combo_configurator", {
    url: "/odoo",
    steps: () => [
        ...stepUtils.goToAppSteps("sale.sale_menu_root", "Open the sales app"),
        ...tourUtils.createNewSalesOrder(),
        ...tourUtils.selectCustomer("Test Partner"),
        ...tourUtils.addProduct("Combo product"),
        comboConfiguratorTourUtils.assertComboCount(2),
        comboConfiguratorTourUtils.assertComboItemCount("Combo A", 2),
        comboConfiguratorTourUtils.assertComboItemCount("Combo B", 2),
        comboConfiguratorTourUtils.assertQuantity(1),
        comboConfiguratorTourUtils.assertPrice("25.00"),
        comboConfiguratorTourUtils.increaseQuantity(),
        comboConfiguratorTourUtils.assertQuantity(2),
        comboConfiguratorTourUtils.assertPrice("50.00"),
        comboConfiguratorTourUtils.decreaseQuantity(),
        comboConfiguratorTourUtils.assertQuantity(1),
        comboConfiguratorTourUtils.assertPrice("25.00"),
        comboConfiguratorTourUtils.setQuantity(3),
        comboConfiguratorTourUtils.assertQuantity(3),
        comboConfiguratorTourUtils.assertPrice("75.00"),
        comboConfiguratorTourUtils.assertConfirmButtonDisabled(),
        comboConfiguratorTourUtils.selectComboItem("Product A2"),
        comboConfiguratorTourUtils.selectComboItem("Product B2"),
        comboConfiguratorTourUtils.assertConfirmButtonEnabled(),
        comboConfiguratorTourUtils.selectComboItem("Product A1"),
        productConfiguratorTourUtils.selectAttribute(
            "Product A1",
            "No variant attribute",
            "A",
        ),
        ...productConfiguratorTourUtils.saveConfigurator(),
        comboConfiguratorTourUtils.assertPrice("90.00"),
        comboConfiguratorTourUtils.selectComboItem("Product A1"),
        ...productConfiguratorTourUtils.selectAndSetCustomAttribute(
            "Product A1",
            "No variant attribute",
            "B",
            "Some custom value",
        ),
        ...productConfiguratorTourUtils.saveConfigurator(),
        comboConfiguratorTourUtils.assertPrice("93.00"),
        ...comboConfiguratorTourUtils.saveConfigurator(),
        tourUtils.checkSOLDescriptionContains("Combo product x 3"),
        tourUtils.checkSOLDescriptionContains(
            "Product A1",
            "No variant attribute: B: Some custom value",
        ),
        tourUtils.checkSOLDescriptionContains("Product B2"),
        {
            content: "Verify the combo item quantities",
            trigger: 'td[name="product_qty"]:contains(3.00)',
        },
        {
            content: "Verify the first combo item's unit price",
            trigger: 'td[name="price_unit"]:contains(18.50)',
        },
        {
            content: "Verify the second combo item's unit price",
            trigger: 'td[name="price_unit"]:contains(12.50)',
        },
        {
            content: "Verify the order's total price",
            trigger: "div.oe_subtotal_footer:contains(93.00)",
        },
        tourUtils.editLineMatching("Combo product x 3"),
        tourUtils.editConfiguration(),
        comboConfiguratorTourUtils.setQuantity(2),
        comboConfiguratorTourUtils.assertComboItemSelected("Product A1"),
        comboConfiguratorTourUtils.assertComboItemSelected("Product B2"),
        comboConfiguratorTourUtils.selectComboItem("Product A2"),
        ...comboConfiguratorTourUtils.saveConfigurator(),
        tourUtils.checkSOLDescriptionContains("Combo product x 2"),
        tourUtils.checkSOLDescriptionContains("Product A2"),
        tourUtils.checkSOLDescriptionContains("Product B2"),
        {
            content: "Verify the combo item quantities",
            trigger: 'td[name="product_qty"]:contains(2.00)',
        },
        {
            content: "Verify the first combo item's unit price",
            trigger: 'td[name="price_unit"]:contains(12.50)',
        },
        {
            content: "Verify the second combo item's unit price",
            trigger: 'td[name="price_unit"]:contains(12.50)',
        },
        {
            content: "Verify the order's total price",
            trigger: "div.oe_subtotal_footer:contains(50.00)",
        },
        ...stepUtils.saveForm(),
    ],
});

registry
    .category("web_tour.tours")
    .add("sale_combo_configurator_with_optional_products", {
        url: "/odoo",
        steps: () => [
            ...stepUtils.goToAppSteps("sale.sale_menu_root", "Open the sales app"),
            ...tourUtils.createNewSalesOrder(),
            ...tourUtils.selectCustomer("Test Partner"),
            ...tourUtils.addProduct("Combo product"),
            comboConfiguratorTourUtils.selectComboItem("Product B2"),
            ...comboConfiguratorTourUtils.saveConfigurator(),
            productConfiguratorTourUtils.addOptionalProduct("Optional product"),
            {
                content: "verify that we cannot reduce main product quantity",
                trigger: ':not(button[name="sale_quantity_button_minus"])',
            },
            {
                content: "verify that we cannot increase main product quantity",
                trigger: ':not(button[name="sale_quantity_button_plus"])',
            },
            ...productConfiguratorTourUtils.saveConfigurator(),
            tourUtils.checkSOLDescriptionContains("Combo product"),
            tourUtils.checkSOLDescriptionContains("Product B2"),
            tourUtils.checkSOLDescriptionContains("Optional product"),
            ...stepUtils.saveForm(),
        ],
    });
