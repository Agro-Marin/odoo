/** @odoo-module native */
import { normalize } from "@web/core/l10n/utils";

// Product-catalogue display/search logic extracted from PosStore. These are pure
// functions of the store: PosStore keeps thin delegating getters/methods (the
// patchable, consumer-facing API) so the modules that patch PosStore.prototype
// and the components reading `pos.productsToDisplay` are unaffected. Cross-calls
// go through `pos.<method>()` so a module's patch still applies.

export function getExcludedProductIds(pos) {
    return [
        pos.config.tip_product_id?.product_tmpl_id?.id,
        ...pos.config._pos_special_products_ids.map(
            (id) => pos.models["product.product"].get(id)?.product_tmpl_id?.id,
        ),
    ].filter(Boolean);
}

export function areAllProductsSpecial(pos, products) {
    const specialDisplayProductIds = pos.config._pos_special_display_products_ids || [];
    return (
        specialDisplayProductIds.length >= products.length &&
        products.every((product) => specialDisplayProductIds.includes(product.id))
    );
}

export function orderProductBySequenceAndFav(pos, products) {
    const searchWord = pos.searchProductWord.trim();
    const isSearchByWord = searchWord !== "";
    return isSearchByWord
        ? products.sort((a, b) => b.is_favorite - a.is_favorite)
        : products.sort((a, b) => {
              if (b.is_favorite !== a.is_favorite) {
                  return b.is_favorite - a.is_favorite;
              } else if (a.pos_sequence !== b.pos_sequence) {
                  return a.pos_sequence - b.pos_sequence;
              }
              return a.name.localeCompare(b.name);
          });
}

export function getProductsBySearchWord(searchWord, products) {
    const query = normalize(searchWord);
    const matches = [];

    for (const product of products) {
        const searchStr = product.searchString;

        if (searchStr.includes(query)) {
            const normName = product.normalizedName;
            matches.push({
                product: product,
                index: normName.indexOf(query),
                name: normName,
            });
        }
    }

    matches.sort(
        (a, b) =>
            (a.index === -1) - (b.index === -1) ||
            a.index - b.index ||
            (a.name === b.name ? 0 : a.name > b.name ? 1 : -1),
    );

    return matches.map((m) => m.product);
}

export function computeProductsToDisplay(pos) {
    const searchWord = pos.searchProductWord.trim();
    const allProducts = pos.models["product.template"].getAll();
    let list = [];
    const isSearchByWord = searchWord !== "";

    if (isSearchByWord) {
        // The "reset category when a search begins" transition lives in a
        // reactive effect (see PosStore.setup), not here — this is read during
        // render and must stay pure.
        list = pos.getProductsBySearchWord(
            searchWord,
            pos.selectedCategory?.id
                ? pos.selectedCategory.associatedProducts
                : allProducts,
        );
    } else {
        if (pos.selectedCategory?.id) {
            list = pos.selectedCategory.associatedProducts;
        } else {
            list = allProducts;
        }
    }

    if (!list || list.length === 0) {
        return [];
    }

    const filteredList = [];
    const excludedProductIds = new Set(pos.getExcludedProductIds());
    const availableCateg = new Set(
        (pos.config.iface_available_categ_ids || []).map((c) => c.id),
    );

    for (const p of list) {
        if (filteredList.length >= 100) {
            break;
        }

        if (excludedProductIds.has(p.id) || !p.canBeDisplayed) {
            continue;
        }

        if (
            availableCateg.size &&
            !pos.config._pos_special_display_products_ids?.includes(p.id) &&
            !p.pos_categ_ids.some((c) => availableCateg.has(c.id))
        ) {
            continue;
        }

        filteredList.push(p);
    }

    if (
        !isSearchByWord &&
        !pos.selectedCategory?.id &&
        pos.areAllProductsSpecial(filteredList)
    ) {
        return [];
    }

    return pos.orderProductBySequenceAndFav(filteredList);
}

export function computeProductToDisplayByCateg(pos) {
    const sortedProducts = pos.productsToDisplay;
    if (!pos.config.iface_group_by_categ) {
        return sortedProducts.length ? [["0", sortedProducts]] : [];
    }

    const results = [];
    const searchWord = pos.searchProductWord.trim();
    const byCateg = pos.models["product.template"].getAllBy("pos_categ_ids");
    const selectedCategoryIds = !pos.selectedCategory
        ? pos.models["pos.category"].map((c) => c.id)
        : pos.selectedCategory.getAllChildren().map((c) => c.id);

    // Sorting in place the categories according to their sequence in the database
    selectedCategoryIds.sort((a, b) => {
        const categA = pos.models["pos.category"].get(a);
        const categB = pos.models["pos.category"].get(b);

        // All category with a parent will be at the end
        if (categA.parent_id && !categB.parent_id) {
            return 1;
        } else if (!categA.parent_id && categB.parent_id) {
            return -1;
        }

        return categA.sequence - categB.sequence;
    });

    if (!pos.selectedCategory) {
        // In case of no category selected, we want to display products without category in
        // a "Without category" category at the end of the list.
        // We use the default sortedProducts order to keep the same order as in the non
        // group by category mode.
        const productWithoutCategory = sortedProducts.filter(
            (p) => !p.pos_categ_ids.length,
        );
        byCateg["0"] = productWithoutCategory;
        selectedCategoryIds.push("0");
    }

    for (const catId of selectedCategoryIds) {
        const products = byCateg[catId] || [];
        const filtered = searchWord
            ? pos.getProductsBySearchWord(searchWord, products)
            : products;

        if (filtered.length) {
            // Its advised to not use group by categ with too much products in differents
            // categories, but in case of we end up with too much products, we slice them in
            // group of 100 to avoid freezing the browser tab.
            // We cannot just slice the products to display and keep the same category, because
            // we want to avoid having categories with only few products displayed and others
            // with a lot of products not displayed.
            const sorted = pos.orderProductBySequenceAndFav(filtered);
            results.push([catId, sorted.splice(0, 100)]);
        }
    }

    return results;
}
