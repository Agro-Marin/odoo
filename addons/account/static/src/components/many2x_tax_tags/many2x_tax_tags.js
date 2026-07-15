/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/fields/relational/many2many_tags/many2many_tags_field";

export class Many2XTaxTagsAutocomplete extends Many2XAutocomplete {
    // Always offer "Search More" for tax tags; the base gates the option on this
    // hook and builds it via buildSearchMoreSuggestion (which wires onSearchMore).
    addSearchMoreSuggestion() {
        return true;
    }

    async onSearchMore(request) {
        const { getDomain, context, fieldString } = this.props;
        // Don't mutate the shared props.context object; derive a copy instead.
        const searchContext = request.length
            ? { ...context, search_default_name: request }
            : context;
        const title = _t("Search: %s", fieldString);
        this.selectCreate({
            domain: getDomain(),
            context: searchContext,
            title,
        });
    }
}

export class Many2ManyTaxTagsField extends Many2ManyTagsField {
    static components = {
        ...Many2ManyTagsField.components,
        Many2XAutocomplete: Many2XTaxTagsAutocomplete,
    };
}

export const many2ManyTaxTagsField = {
    ...many2ManyTagsField,
    component: Many2ManyTaxTagsField,
    additionalClasses: ['o_field_many2many_tags']
};

registry.category("fields").add("many2many_tax_tags", many2ManyTaxTagsField);
