import { registry } from "@web/core/registry";
import configuratorTourUtils from "@sale/js/tours/product_configurator_tour_utils";
import * as wsTourUtils from "@website_sale/js/tours/tour_utils";
import stockConfiguratorTourUtils from "@website_sale_stock/js/tours/product_configurator_tour_utils";

registry.category("web_tour.tours").add("website_sale_stock_product_configurator", {
    url: "/shop?search=Main product",
    steps: () => [
        ...wsTourUtils.addToCart({
            productName: "Main product",
            search: false,
            expectUnloadPage: true,
        }),
        configuratorTourUtils.assertProductQuantity("Main product", 1),
        configuratorTourUtils.setProductQuantity("Main product", 0),
        configuratorTourUtils.assertProductQuantity("Main product", 1),
        {
            content: "check that decrease button is disabled",
            trigger: `.modal button[name=sale_quantity_button_minus]:disabled`,
        },
        configuratorTourUtils.setProductQuantity("Main product", 20),
        configuratorTourUtils.assertProductQuantity("Main product", 10),
        {
            content: "check that increase button is disabled",
            trigger: `.modal button[name=sale_quantity_button_plus]:disabled`,
        },
        ...stockConfiguratorTourUtils.assertOptionalProductOutOfStock(
            "Optional product (Out of stock)",
        ),
        configuratorTourUtils.selectAttribute("Optional product", "Stock", "In stock"),
        configuratorTourUtils.addOptionalProduct("Optional product (In stock)"),
        configuratorTourUtils.selectAttribute(
            "Optional product",
            "Stock",
            "Out of stock",
        ),
        ...stockConfiguratorTourUtils.assertProductOutOfStock(
            "Optional product (Out of stock)",
        ),
        configuratorTourUtils.assertFooterButtonsDisabled(),
        configuratorTourUtils.removeOptionalProduct("Optional product"),
        {
            content: "Proceed to checkout",
            trigger: "button:contains(Go to Checkout)",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "Verify the quantity in the cart",
            trigger: 'div.o_cart_product input.quantity[value="10"]',
        },
    ],
});
