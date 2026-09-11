import { registry } from "@web/core/registry";
import configuratorTourUtils from "@sale/js/tours/combo_configurator_tour_utils";
import * as wsTourUtils from "@website_sale/js/tours/tour_utils";
import stockConfiguratorTourUtils from "@website_sale_stock/js/tours/combo_configurator_tour_utils";

registry.category("web_tour.tours").add("website_sale_stock_combo_configurator", {
    url: "/shop?search=Combo product",
    steps: () => [
        ...wsTourUtils.addToCart({
            productName: "Combo product",
            search: false,
            expectUnloadPage: true,
        }),
        configuratorTourUtils.assertQuantity(1),
        configuratorTourUtils.setQuantity(0),
        configuratorTourUtils.assertQuantity(1),
        {
            content: "Verify that the quantity decrease button is disabled",
            trigger: `
                    .sale-combo-configurator-dialog
                    button[name=sale_quantity_button_minus]:disabled
                `,
        },
        configuratorTourUtils.setQuantity(3),
        stockConfiguratorTourUtils.assertQuantityNotAvailable("Test product"),
        configuratorTourUtils.setQuantity(2),
        configuratorTourUtils.selectComboItem("Test product"),
        stockConfiguratorTourUtils.assertAllQuantitySelected("Test product"),
        configuratorTourUtils.setQuantity(3),
        configuratorTourUtils.assertQuantity(2),
        {
            content: "Verify that the quantity increase button is disabled",
            trigger: `
                    .sale-combo-configurator-dialog
                    button[name=sale_quantity_button_plus]:disabled
                `,
        },
    ],
});
