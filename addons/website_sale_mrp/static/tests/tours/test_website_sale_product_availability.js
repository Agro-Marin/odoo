/** @odoo-module native */

import { registry } from "@web/core/registry";
import { addToCart, searchProduct } from "@website_sale/js/tours/tour_utils";

registry.category("web_tour.tours").add("test_website_sale_availability_kit", {
    url: "/shop",
    steps: () => [
        ...addToCart({ productName: "Consumable Component", expectUnloadPage: true }),
        { trigger: "a[href='/shop']", run: "click", expectUnloadPage: true },
        ...addToCart({ productName: "Component A", expectUnloadPage: true }),
        { trigger: ".availability_messages:contains(99)" },
        { trigger: "a[href='/shop']", run: "click", expectUnloadPage: true },
        ...searchProduct("Super Kit Product"),
        {
            trigger: "a:contains('Super Kit Product')",
            run: "click",
            expectUnloadPage: true,
        },
        { trigger: ".availability_messages:contains(19)" },
        { trigger: "#add_to_cart", run: "click" },
        { trigger: ".availability_messages:contains(18)" },
        { trigger: "a[href='/shop']", run: "click", expectUnloadPage: true },
        ...searchProduct("Kit Product"),
        { trigger: "a:contains('Kit Product')", run: "click", expectUnloadPage: true },
        { trigger: ".availability_messages:contains(19)" },
        { trigger: "#add_to_cart", run: "click" },
        { trigger: ".availability_messages:contains(18)" },
        { trigger: "a[href='/shop']", run: "click", expectUnloadPage: true },
        ...addToCart({ productName: "Component A", expectUnloadPage: true }),
        { trigger: ".availability_messages:contains(92)" },
        { trigger: "a[href='/shop']", run: "click", expectUnloadPage: true },
        ...searchProduct("Component B"),
        { trigger: "a:contains('Component B')", run: "click", expectUnloadPage: true },
        { trigger: "#add_to_cart", run: "click" },
        { trigger: ".availability_messages:contains(89)" },
        { trigger: "a[href='/shop']", run: "click", expectUnloadPage: true },
        ...searchProduct("Super Kit Product"),
        {
            trigger: "a:contains('Super Kit Product')",
            run: "click",
            expectUnloadPage: true,
        },
        { trigger: ".availability_messages:contains(17)" },
    ],
});
