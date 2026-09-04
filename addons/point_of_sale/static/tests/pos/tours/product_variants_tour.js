import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as ProductConfiguratorPopup from "@point_of_sale/../tests/pos/tours/utils/product_configurator_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import { registry } from "@web/core/registry";

function check_variant_price(product, choices, price) {
    const steps = [...ProductScreen.clickDisplayedProduct(product)];
    for (const choice of choices) {
        steps.push(...ProductConfiguratorPopup.pickRadio(choice));
    }
    steps.push(
        Dialog.confirm(),
        ...ProductScreen.totalAmountIs(price),
        ...ProductScreen.clickNumpad("⌫"),
        ...ProductScreen.clickNumpad("⌫"),
    );
    return steps.flat();
}

registry.category("web_tour.tours").add("test_integration_dynamic_variant_price", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            check_variant_price("A dynamic product", ["dyn1"], "1.00"),
            check_variant_price("A dynamic product", ["dyn2"], "6.00"),
            check_variant_price("A dynamic product", ["dyn3"], "11.00"),
            Chrome.endTour(),
        ].flat(),
});

registry.category("web_tour.tours").add("test_integration_always_variant_price", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            check_variant_price("A always product", ["S"], "1.00"),
            check_variant_price("A always product", ["M"], "6.00"),
            Chrome.endTour(),
        ].flat(),
});

registry.category("web_tour.tours").add("test_integration_never_variant_price", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            check_variant_price("A never product", ["extra"], "1.00"),
            check_variant_price("A never product", ["second"], "6.00"),
            Chrome.endTour(),
        ].flat(),
});

registry
    .category("web_tour.tours")
    .add("test_integration_dynamic_always_variant_price", {
        steps: () =>
            [
                Chrome.startPoS(),
                Dialog.confirm("Open Register"),
                check_variant_price("A dyn/alw product", ["dyn1", "S"], "1.00"),
                check_variant_price("A dyn/alw product", ["dyn1", "M"], "6.00"),
                check_variant_price("A dyn/alw product", ["dyn2", "S"], "11.00"),
                check_variant_price("A dyn/alw product", ["dyn2", "M"], "16.00"),
                check_variant_price("A dyn/alw product", ["dyn3", "S"], "21.00"),
                check_variant_price("A dyn/alw product", ["dyn3", "M"], "26.00"),
                Chrome.endTour(),
            ].flat(),
    });

registry
    .category("web_tour.tours")
    .add("test_integration_dynamic_never_variant_price", {
        steps: () =>
            [
                Chrome.startPoS(),
                Dialog.confirm("Open Register"),
                check_variant_price("A dyn/nev product", ["dyn1", "extra"], "1.00"),
                check_variant_price("A dyn/nev product", ["dyn1", "second"], "6.00"),
                check_variant_price("A dyn/nev product", ["dyn2", "extra"], "11.00"),
                check_variant_price("A dyn/nev product", ["dyn2", "second"], "16.00"),
                check_variant_price("A dyn/nev product", ["dyn3", "extra"], "21.00"),
                check_variant_price("A dyn/nev product", ["dyn3", "second"], "26.00"),
                Chrome.endTour(),
            ].flat(),
    });

registry.category("web_tour.tours").add("test_integration_always_never_variant_price", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            check_variant_price("A alw/nev product", ["S", "extra"], "1.00"),
            check_variant_price("A alw/nev product", ["S", "second"], "6.00"),
            check_variant_price("A alw/nev product", ["M", "extra"], "11.00"),
            check_variant_price("A alw/nev product", ["M", "second"], "16.00"),
            Chrome.endTour(),
        ].flat(),
});

registry
    .category("web_tour.tours")
    .add("test_integration_dynamic_always_never_variant_price", {
        steps: () =>
            [
                Chrome.startPoS(),
                Dialog.confirm("Open Register"),

                check_variant_price(
                    "A dyn/alw/nev product",
                    ["dyn1", "S", "extra"],
                    "1.00",
                ),
                check_variant_price(
                    "A dyn/alw/nev product",
                    ["dyn1", "S", "second"],
                    "1.50",
                ),
                check_variant_price(
                    "A dyn/alw/nev product",
                    ["dyn1", "M", "extra"],
                    "6.00",
                ),
                check_variant_price(
                    "A dyn/alw/nev product",
                    ["dyn1", "M", "second"],
                    "6.50",
                ),

                check_variant_price(
                    "A dyn/alw/nev product",
                    ["dyn2", "S", "extra"],
                    "11.00",
                ),
                check_variant_price(
                    "A dyn/alw/nev product",
                    ["dyn2", "S", "second"],
                    "11.50",
                ),
                check_variant_price(
                    "A dyn/alw/nev product",
                    ["dyn2", "M", "extra"],
                    "16.00",
                ),
                check_variant_price(
                    "A dyn/alw/nev product",
                    ["dyn2", "M", "second"],
                    "16.50",
                ),
                Chrome.endTour(),
            ].flat(),
    });

registry.category("web_tour.tours").add("test_image_variants_displayed", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.clickDisplayedProduct("Image Product"),
            ProductConfiguratorPopup.checkImageVariantVisible(),
            ProductConfiguratorPopup.checkImageVariantTextVisible("First Image"),
            ProductConfiguratorPopup.checkImageVariantTextVisible("Second Image"),
            ProductConfiguratorPopup.checkImagePriceExtraVisible("$ 20"),
        ].flat(),
});

registry.category("web_tour.tours").add("test_search_variant_by_default_code", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ...ProductScreen.searchProduct("REF-SIZE-M"),
            {
                // The search box is debounced, so wait for it to have applied
                // before clicking: otherwise the click lands while
                // pos.searchProductWord is still empty.
                content: "the search narrowed the list to the referenced variant",
                trigger:
                    ".product-list article:only-child .product-name:contains('A always product')",
            },
            ProductScreen.clickDisplayedProduct("A always product"),
            // The reference identifies the M variant by itself, so the
            // configurator has nothing left to ask and the line is added
            // straight away. M costs 6.0 where S, the first value and the one
            // picked before this fix, costs 1.0.
            ...ProductScreen.selectedOrderlineHas("A always product", "1.0", "6.0"),
            Chrome.endTour(),
        ].flat(),
});
