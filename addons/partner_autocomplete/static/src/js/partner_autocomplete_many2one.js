/** @odoo-module native */
import { registerField } from "@web/fields/_registry";
import { useService } from "@web/core/utils/hooks";
import {
  computeM2OProps,
  Many2One,
} from "@web/fields/relational/many2one/many2one";
import {
  buildM2OFieldDescription,
  Many2OneField,
} from "@web/fields/relational/many2one/many2one_field";
import { Component } from "@odoo/owl";
import {
  Many2XAutocomplete,
  useOpenMany2XRecord,
} from "@web/fields/relational/many2x_autocomplete";

import { usePartnerAutocomplete } from "@partner_autocomplete/js/partner_autocomplete_core";
import { PartnerAutoComplete } from "@partner_autocomplete/js/partner_autocomplete_component";

export class PartnerMany2XAutocomplete extends Many2XAutocomplete {
  static components = {
    ...super.components,
    AutoComplete: PartnerAutoComplete,
  };
}
export class PartnerMany2One extends Many2One {
  static components = {
    ...super.components,
    Many2XAutocomplete: PartnerMany2XAutocomplete,
  };
}

export class PartnerAutoCompleteMany2one extends Component {
  static template = "partner_autocomplete.PartnerAutoCompleteMany2one";
  static components = { Many2One: PartnerMany2One };
  static props = { ...Many2OneField.props };

  setup() {
    super.setup();
    this.orm = useService("orm");
    this.partnerAutocomplete = usePartnerAutocomplete();
    this.openRecord = useOpenMany2XRecord({
      resModel: this.props.record.fields[this.props.name].relation,
      activeActions: {
        create: this.props.canCreate,
        createEdit: this.props.canCreateEdit,
        write: this.props.canWrite,
      },
      isToMany: false,
      onRecordSaved: (record) =>
        this.props.record.update({
          [this.props.name]: {
            id: record.resId,
            display_name: record.data.display_name || record.data.name,
          },
        }),
      onRecordDiscarded: () => this.props.record.update(false),
      fieldString:
        this.props.string || this.props.record.fields[this.props.name].string,
    });
  }

  get m2oProps() {
    return {
      ...computeM2OProps(this.props),
      otherSources: this.sources,
    };
  }

  get sources() {
    if (!this.props.canCreate) {
      return [];
    }
    return [
      this.partnerAutocomplete.makeAutocompleteSource({
        cssClass: "partner_autocomplete_dropdown_many2one",
        getCountryId: () => false,
        onSelectOption: (suggestion) =>
          this.onSelectPartnerAutocompleteOption(suggestion),
      }),
    ];
  }

  async onSelectPartnerAutocompleteOption(option) {
    const data = await this.partnerAutocomplete.getCreateData(option);
    if (!data?.company) {
      return;
    }
    const context = {
      default_is_company: true,
    };

    // Only real partner fields become defaults; enrichment bookkeeping
    // (query/description/logo/error/…) is stripped first.
    const company = this.partnerAutocomplete.stripInternalKeys(data.company);
    for (const [key, val] of Object.entries(company)) {
      context["default_" + key] = val && val.id ? val.id : val;
    }

    if (data.logo) {
      context.default_image_1920 = data.logo;
    }

    return this.openRecord({ context });
  }
}

export const PartnerAutoCompleteMany2oneField = {
  ...buildM2OFieldDescription(PartnerAutoCompleteMany2one),
};

registerField("res_partner_many2one", PartnerAutoCompleteMany2oneField, {
  force: true,
});
