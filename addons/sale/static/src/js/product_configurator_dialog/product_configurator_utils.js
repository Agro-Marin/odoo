/** @odoo-module native */
/**
 * Pure helpers for the product configurator's combination / exclusion logic.
 *
 * Extracted from `ProductConfiguratorDialog` so the algorithm can be unit-tested in
 * isolation — no OWL component, env, RPC or DOM required. Every function operates on
 * plain "product" objects as returned by `/sale/product_configurator/get_values`
 * (`{product_tmpl_id, parent_product_tmpl_id, attribute_lines, exclusions,
 * parent_exclusions, archived_combinations, ...}`), and, where a product must be
 * looked up, on an explicit pool of such products (the dialog passes its main +
 * optional products).
 */

/**
 * Return the selected PTAV ids of a product, across all its attribute lines.
 *
 * @param {Object} product
 * @return {Number[]}
 */
export function getCombination(product) {
    return product.attribute_lines.flatMap((ptal) => ptal.selected_attribute_value_ids);
}

/**
 * Find a product by its template id within a pool of products.
 *
 * @param {Object[]} products
 * @param {Number} productTmplId
 * @return {Object|undefined}
 */
export function findProduct(products, productTmplId) {
    return products.find((p) => p.product_tmpl_id === productTmplId);
}

/**
 * Return the child (dependent) products of a given product template.
 *
 * @param {Object[]} products
 * @param {Number} productTmplId
 * @return {Object[]}
 */
export function getChildProducts(products, productTmplId) {
    return products.filter((p) => p.parent_product_tmpl_id === productTmplId);
}

/**
 * Return the selected PTAVs of a product's parent, or `[]` if it has no parent.
 *
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
 * Check whether a product has a valid combination, i.e. none of its selected PTAVs
 * is currently excluded.
 *
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
 * Recompute the `excluded` flag on every PTAV of `product` (and, recursively, of its
 * child products) from three sources: the product's own exclusions, its parent's
 * exclusions, and its archived combinations. Mutates the PTAV objects in place.
 *
 * @param {Object[]} products The pool used to resolve parents and children.
 * @param {Object} product The product whose exclusions to (re)compute.
 */
export function checkExclusions(products, product) {
    const combination = getCombination(product);
    const exclusions = product.exclusions;
    const parentExclusions = product.parent_exclusions;
    const archivedCombinations = product.archived_combinations;
    const parentCombination = getParentsCombination(products, product);
    const childProducts = getChildProducts(products, product.product_tmpl_id);
    const ptavList = product.attribute_lines.flatMap((ptal) => ptal.attribute_values);
    ptavList.forEach((ptav) => (ptav.excluded = false)); // Reset all the values

    if (exclusions) {
        for (const ptavId of combination) {
            for (const excludedPtavId of exclusions[ptavId] || []) {
                const excludedPtav = ptavList.find(
                    (ptav) => ptav.id === excludedPtavId,
                );
                if (excludedPtav) {
                    excludedPtav.excluded = true; // Assign only if the element exists
                }
            }
        }
    }
    if (parentCombination) {
        for (const ptavId of parentCombination) {
            for (const excludedPtavId of parentExclusions[ptavId] || []) {
                const ptav = ptavList.find((ptav) => ptav.id === excludedPtavId);
                if (ptav) {
                    ptav.excluded = true; // Assign only if the element exists
                }
            }
        }
    }
    if (archivedCombinations) {
        for (const excludedCombination of archivedCombinations) {
            const ptavCommon = excludedCombination.filter((ptav) =>
                combination.includes(ptav),
            );
            if (ptavCommon.length === combination.length) {
                for (const excludedPtavId of ptavCommon) {
                    const ptav = ptavList.find((ptav) => ptav.id === excludedPtavId);
                    if (ptav) {
                        ptav.excluded = true;
                    }
                }
            } else if (ptavCommon.length === combination.length - 1) {
                // In this case we only need to disable the remaining ptav
                const disabledPtavId = excludedCombination.find(
                    (ptav) => !combination.includes(ptav),
                );
                const excludedPtav = ptavList.find(
                    (ptav) => ptav.id === disabledPtavId,
                );
                if (excludedPtav) {
                    excludedPtav.excluded = true;
                }
            }
        }
    }
    for (const childProduct of childProducts) {
        checkExclusions(products, childProduct);
    }
}
