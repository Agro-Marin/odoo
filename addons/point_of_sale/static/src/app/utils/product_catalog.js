/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { normalize } from "@web/core/l10n/utils";
const log = makeLogger("pos.catalog");

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
    const endSearch = log.perf("getProductsBySearchWord");

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
    endSearch({ query, candidates: products.length, matches: matches.length });

    return matches.map((m) => m.product);
}

export function computeProductsToDisplay(pos) {
    const searchWord = pos.searchProductWord.trim();
    const allProducts = pos.models["product.template"].getAll();
    let list;
    const isSearchByWord = searchWord !== "";
    const endCompute = log.perf("computeProductsToDisplay");

    if (isSearchByWord) {
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
        endCompute({ searchWord, category: pos.selectedCategory?.id, result: 0 });
        return [];
    }

    const filteredList = [];
    const excludedProductIds = new Set(pos.getExcludedProductIds());
    const availableCateg = new Set(
        (pos.config.iface_available_categ_ids || []).map((c) => c.id),
    );
    let scanned = 0;
    let excluded = 0;
    let hiddenByCategory = 0;

    for (const p of list) {
        if (filteredList.length >= 100) {
            break;
        }
        scanned++;

        if (excludedProductIds.has(p.id) || !p.canBeDisplayed) {
            excluded++;
            continue;
        }

        if (
            availableCateg.size &&
            !pos.config._pos_special_display_products_ids?.includes(p.id) &&
            !p.pos_categ_ids.some((c) => availableCateg.has(c.id))
        ) {
            hiddenByCategory++;
            continue;
        }

        filteredList.push(p);
    }

    const allSpecial =
        !isSearchByWord &&
        !pos.selectedCategory?.id &&
        pos.areAllProductsSpecial(filteredList);
    endCompute({
        searchWord,
        category: pos.selectedCategory?.id,
        candidates: list.length,
        scanned,
        excluded,
        hiddenByCategory,
        capped: scanned < list.length,
        allSpecial,
        result: allSpecial ? 0 : filteredList.length,
    });
    if (allSpecial) {
        return [];
    }

    return pos.orderProductBySequenceAndFav(filteredList);
}

export function computeProductToDisplayByCateg(pos) {
    const sortedProducts = pos.productsToDisplay;
    if (!pos.config.iface_group_by_categ) {
        return sortedProducts.length ? [["0", sortedProducts]] : [];
    }

    const endCompute = log.perf("computeProductToDisplayByCateg");
    const results = [];
    const searchWord = pos.searchProductWord.trim();
    const byCateg = pos.models["product.template"].getAllBy("pos_categ_ids");
    const selectedCategoryIds = !pos.selectedCategory
        ? pos.models["pos.category"].map((c) => c.id)
        : pos.selectedCategory.getAllChildren().map((c) => c.id);

    selectedCategoryIds.sort((a, b) => {
        const categA = pos.models["pos.category"].get(a);
        const categB = pos.models["pos.category"].get(b);

        if (categA.parent_id && !categB.parent_id) {
            return 1;
        } else if (!categA.parent_id && categB.parent_id) {
            return -1;
        }

        return categA.sequence - categB.sequence;
    });

    if (!pos.selectedCategory) {
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
            const sorted = pos.orderProductBySequenceAndFav(filtered);
            results.push([catId, sorted.splice(0, 100)]);
        }
    }
    endCompute({
        searchWord,
        category: pos.selectedCategory?.id,
        categories: selectedCategoryIds.length,
        groups: results.length,
    });

    return results;
}
