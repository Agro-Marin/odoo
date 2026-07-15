/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";
import { Many2One } from "@web/fields/relational/many2one/many2one";
import { Many2OneField, buildM2OFieldDescription } from "@web/fields/relational/many2one/many2one_field";

export class Many2XAccountAccountAutocomplete extends Many2XAutocomplete {
    addSearchMoreSuggestion(options) {
        if (/\d/.test(options.request)) {
            return super.addSearchMoreSuggestion(options);
        }
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

export class Many2OneAccountAccount extends Many2One {
    static components = {
        ...Many2One.components,
        Many2XAutocomplete: Many2XAccountAccountAutocomplete,
    };
}

export class Many2OneFieldAccountAccount extends Many2OneField {
    static components = {
        ...Many2OneField.components,
        Many2One: Many2OneAccountAccount,
    };
}

registry.category("fields").add("many2one_account_account", {
    ...buildM2OFieldDescription(Many2OneFieldAccountAccount),
    additionalClasses: ["o_field_many2one"],
});
