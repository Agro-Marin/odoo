import * as ProductConfigurator from "@point_of_sale/../tests/pos/tours/utils/product_configurator_util";

export function addOptionalProduct(productName, quantity, configurable) {
    const step = [
        {
            content: `Verify that the optional product "${productName}" is available in the list.`,
            trigger: `.optional-product-line .product-name:contains("${productName}")`,
        },
        {
            content: `Click the "+ Add" button to add the optional product "${productName}" to the cart.`,
            trigger: `.optional-product-line .cart-buttons button:contains("+ Add")`,
            run: "click",
        },
    ];

    if (configurable) {
        step.push(
            ...ProductConfigurator.pickColor("Blue"),
            ...ProductConfigurator.pickSelect("Metal"),
            ...ProductConfigurator.pickRadio("wool"),
            {
                trigger:
                    ".o-overlay-item:nth-child(2) .modal-footer button:contains('Add')",
                run: "click",
            },
        );
    }

    if (quantity > 1) {
        for (let i = 1; i < quantity; i++) {
            step.push(
                {
                    content: `Verify the quantity of "${productName}" is updated to ${i}.`,
                    trigger: `.optional-product-line .cart-buttons input:value("${i}")`,
                },
                {
                    content: `Increase the quantity of "${productName}" by clicking the "+" button.`,
                    trigger: `.optional-product-line .cart-buttons button:eq(1)`,
                    run: "click",
                },
            );
        }
        step.push({
            content: `Click the "Add" button to confirm adding "${productName}" to the order.`,
            trigger: `.modal-footer button:contains("Add")`,
            run: "click",
        });

        return step;
    }
}

export function checkImage(productName, shouldHaveImage = false) {
    const baseSelector = `.modal .optional-product-line:has(.product-name:contains("${productName}"))`;
    const trigger = shouldHaveImage
        ? `${baseSelector}:has(img.product-img)`
        : `${baseSelector}:not(:has(img.product-img))`;

    return {
        content: `Check image visibility for optional product "${productName}"`,
        trigger,
    };
}
