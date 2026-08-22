/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/fields/relational/many2many_tags";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";

export class Many2XTaxTagsAutocomplete extends Many2XAutocomplete {
    addSearchMoreSuggestion() {
        return true;
    }

    async onSearchMore(request) {
        const { getDomain, context, fieldString } = this.props;
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
    additionalClasses: ["o_field_many2many_tags"],
};

registry.category("fields").add("many2many_tax_tags", many2ManyTaxTagsField);
