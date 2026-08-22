/** @odoo-module native */

/**
 * @param {Object} product
 * @return {Number[]}
 */
export function getCombination(product) {
    return product.attribute_lines.flatMap((ptal) => ptal.selected_attribute_value_ids);
}

/**
 * @param {Object} product
 * @return {Number[]}
 */
export function getVariantCombination(product) {
    return product.attribute_lines
        .filter((ptal) => ptal.create_variant !== "no_variant")
        .flatMap((ptal) => ptal.selected_attribute_value_ids);
}

/**
 * @param {Object[]} products
 * @param {Number} productTmplId
 * @return {Object|undefined}
 */
export function findProduct(products, productTmplId) {
    return products.find((p) => p.product_tmpl_id === productTmplId);
}

/**
 * @param {Object[]} products
 * @param {Number} productTmplId
 * @return {Object[]}
 */
export function getChildProducts(products, productTmplId) {
    return products.filter((p) => p.parent_product_tmpl_id === productTmplId);
}

/**
 * @param {Object[]} products
 * @param {Object} product
 * @return {Number[]}
 */
export function getParentsCombination(products, product) {
    return product.parent_product_tmpl_id
        ? getCombination(findProduct(products, product.parent_product_tmpl_id))
        : [];
}

/**
 * @param {Object} product
 * @return {Boolean}
 */
export function isPossibleCombination(product) {
    return product.attribute_lines.every((ptal) => {
        const selectedPtavIds = new Set(ptal.selected_attribute_value_ids);
        return ptal.attribute_values
            .filter((ptav) => selectedPtavIds.has(ptav.id))
            .every((ptav) => !ptav.excluded);
    });
}

/**
 * @param {Object[]} products
 * @param {Object} product
 */
export function checkExclusions(products, product) {
    const combination = getCombination(product);
    const exclusions = product.exclusions;
    const parentExclusions = product.parent_exclusions;
    const archivedCombinations = product.archived_combinations;
    const parentCombination = getParentsCombination(products, product);
    const childProducts = getChildProducts(products, product.product_tmpl_id);
    const ptavList = product.attribute_lines.flatMap((ptal) => ptal.attribute_values);
    ptavList.forEach((ptav) => (ptav.excluded = false));

    const ptavById = new Map(ptavList.map((ptav) => [ptav.id, ptav]));
    const exclude = (ptavId) => {
        const ptav = ptavById.get(ptavId);
        if (ptav) {
            ptav.excluded = true;
        }
    };

    if (exclusions) {
        for (const ptavId of combination) {
            for (const excludedPtavId of exclusions[ptavId] || []) {
                exclude(excludedPtavId);
            }
        }
    }
    if (parentExclusions) {
        for (const ptavId of parentCombination) {
            for (const excludedPtavId of parentExclusions[ptavId] || []) {
                exclude(excludedPtavId);
            }
        }
    }
    if (archivedCombinations) {
        const variantCombination = new Set(getVariantCombination(product));
        for (const excludedCombination of archivedCombinations) {
            const excludedPtavIds = new Set(excludedCombination);
            const commonCount = [...excludedPtavIds].filter((ptavId) =>
                variantCombination.has(ptavId),
            ).length;
            if (commonCount === variantCombination.size) {
                for (const excludedPtavId of excludedPtavIds) {
                    if (variantCombination.has(excludedPtavId)) {
                        exclude(excludedPtavId);
                    }
                }
            } else if (commonCount === variantCombination.size - 1) {
                for (const ptavId of excludedPtavIds) {
                    if (!variantCombination.has(ptavId)) {
                        exclude(ptavId);
                    }
                }
            }
        }
    }
    for (const childProduct of childProducts) {
        checkExclusions(products, childProduct);
    }
}
