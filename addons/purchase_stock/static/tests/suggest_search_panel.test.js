import { AccountProductCatalogSearchPanel } from "@account/components/product_catalog/search/search_panel";
import { expect, test } from "@odoo/hoot";
import { PurchaseSuggestCatalogSearchPanel } from "@purchase_stock/product_catalog/search/search_panel";

// The Suggest panel renders through account.ProductCatalogSearchPanel, which
// inherits web.SearchPanel. On a small screen web.SearchPanel renders its
// `Small` branch, and that branch uses <Dropdown> -- resolved from the class's
// own `components`. Reassigning `static components` instead of extending it
// shadows the parent's entry and the panel cannot render on mobile.
test("the Suggest search panel keeps the components its parent needs", () => {
    const inherited = Object.keys(AccountProductCatalogSearchPanel.components);
    const declared = Object.keys(PurchaseSuggestCatalogSearchPanel.components);

    expect(inherited.length).toBeGreaterThan(0);
    for (const name of inherited) {
        expect(declared).toInclude(name);
    }
    expect(declared).toInclude("TimePeriodSelectionField");
});
