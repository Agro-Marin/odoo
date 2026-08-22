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
 * This is the combination as the *server routes* understand it: it includes
 * `no_variant` selections, because pricing, naming and variant creation all need them.
 * It is NOT the set to compare against `archived_combinations` — see
 * {@link getVariantCombination}.
 *
 * @param {Object} product
 * @return {Number[]}
 */
export function getCombination(product) {
    return product.attribute_lines.flatMap((ptal) => ptal.selected_attribute_value_ids);
}

/**
 * Return the selected PTAV ids that actually take part in defining a variant.
 *
 * `archived_combinations` is built server-side from
 * `product.product_template_attribute_value_ids.ids` of archived variants, which by
 * construction holds only variant-creating PTAVs. Comparing it against
 * {@link getCombination} therefore compares two different sets: every `no_variant`
 * selection inflates one side, and the archived-combination match silently stops
 * firing. That is why this narrower set exists.
 *
 * @param {Object} product
 * @return {Number[]}
 */
export function getVariantCombination(product) {
    return product.attribute_lines
        .filter((ptal) => ptal.create_variant !== "no_variant")
        .flatMap((ptal) => ptal.selected_attribute_value_ids);
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

    // One index instead of a linear `find` per excluded id: this runs on every PTAV
    // change, for the product and recursively for each of its children.
    const ptavById = new Map(ptavList.map((ptav) => [ptav.id, ptav]));
    const exclude = (ptavId) => {
        const ptav = ptavById.get(ptavId);
        if (ptav) {
            ptav.excluded = true; // Assign only if the element exists
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
        // Guard `parentExclusions`, not `parentCombination`: the latter is the return
        // of `getParentsCombination`, i.e. always an array and so always truthy, which
        // left the dereference below unguarded.
        for (const ptavId of parentCombination) {
            for (const excludedPtavId of parentExclusions[ptavId] || []) {
                exclude(excludedPtavId);
            }
        }
    }
    if (archivedCombinations) {
        // Compare like with like: `archived_combinations` holds the PTAVs of archived
        // *variants*, so it never contains a `no_variant` selection. Measuring it
        // against the full combination makes both branches below unreachable as soon
        // as the template carries one.
        const variantCombination = new Set(getVariantCombination(product));
        for (const excludedCombination of archivedCombinations) {
            const excludedPtavIds = new Set(excludedCombination);
            const commonCount = [...excludedPtavIds].filter((ptavId) =>
                variantCombination.has(ptavId),
            ).length;
            if (commonCount === variantCombination.size) {
                // The current selection *is* the archived combination.
                for (const excludedPtavId of excludedPtavIds) {
                    if (variantCombination.has(excludedPtavId)) {
                        exclude(excludedPtavId);
                    }
                }
            } else if (commonCount === variantCombination.size - 1) {
                // One value away from it: disable the value that would complete it.
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
