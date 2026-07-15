/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { SearchBar } from "@web/search/search_bar/search_bar";

patch(SearchBar.prototype, {
    getPreposition(searchItem) {
        let preposition = super.getPreposition(searchItem);
        // Compare fieldName directly: property-field search items are not in
        // this.fields, so dereferencing this.fields[fieldName].name would crash.
        if (
            searchItem.fieldName === 'payment_date'
            || searchItem.fieldName === 'next_payment_date'
        ) {
            preposition = _t("until");
        }
        return preposition;
    }
});
