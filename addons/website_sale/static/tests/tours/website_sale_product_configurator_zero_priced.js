import { registry } from "@web/core/registry";
import configuratorTourUtils from "@sale/js/tours/product_configurator_tour_utils";
import websiteConfiguratorTourUtils from "@website_sale/js/tours/product_configurator_tour_utils";
import * as wsTourUtils from "@website_sale/js/tours/tour_utils";

registry
    .category("web_tour.tours")
    .add("website_sale_product_configurator_zero_priced", {
        url: "/shop?search=Main product",
        steps: () => [
            ...wsTourUtils.addToCart({
                productName: "Main product",
                search: false,
                expectUnloadPage: true,
            }),
            ...websiteConfiguratorTourUtils.assertOptionalProductZeroPriced(
                "Optional product (Zero-priced)",
            ),
            configuratorTourUtils.selectAttribute(
                "Optional product",
                "Price",
                "Nonzero-priced",
            ),
            configuratorTourUtils.addOptionalProduct(
                "Optional product (Nonzero-priced)",
            ),
            configuratorTourUtils.selectAttribute(
                "Optional product",
                "Price",
                "Zero-priced",
            ),
            ...websiteConfiguratorTourUtils.assertProductZeroPriced(
                "Optional product (Zero-priced)",
            ),
            configuratorTourUtils.assertFooterButtonsDisabled(),
        ],
    });
