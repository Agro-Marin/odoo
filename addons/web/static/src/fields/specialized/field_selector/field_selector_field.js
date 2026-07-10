// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/field_selector/field_selector_field - Model field path selector field for Char columns */

import { Component } from "@odoo/owl";
import { ModelFieldSelector } from "@web/components/model_field_selector/model_field_selector";
import { _t } from "@web/core/l10n/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { formatChar } from "@web/fields/formatters";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class FieldSelectorField extends Component {
    static template = "web.FieldSelectorField";
    static components = { ModelFieldSelector };
    static props = {
        ...standardFieldProps,
        resModel: { type: String, optional: true },
        onlySearchable: { type: Boolean, optional: true },
        allowProperties: { type: Boolean, optional: true },
        followRelations: { type: Boolean, optional: true },
    };

    filter(fieldDef) {
        if (fieldDef.type === "separator") {
            // Don't show properties separator
            return false;
        }
        if (!this.props.allowProperties && fieldDef.type === "properties") {
            return false;
        }
        return !this.props.onlySearchable || fieldDef.searchable;
    }

    async update(value) {
        await this.props.record.update({ [this.props.name]: value });
    }

    //---- Getters ----
    get formattedValue() {
        return formatChar(this.props.record.data[this.props.name]);
    }

    get resModel() {
        const { record } = this.props;
        // ``resModel`` prop may be either a field name (holding the target model)
        // or a literal model name. Only dereference it through ``data`` when it is
        // actually a field on the record; otherwise treat it as a literal. In both
        // cases, fall back to the current record's model when the result is empty.
        let resModel = this.props.resModel;
        if (record.fieldNames.includes(resModel)) {
            resModel = record.data[resModel];
        }
        return resModel || record.resModel;
    }

    get selectorProps() {
        return {
            allowEmpty: !this.props.required,
            path: this.props.record.data[this.props.name],
            resModel: this.resModel,
            readonly: this.props.readonly,
            update: this.update.bind(this),
            isDebugMode: !!this.env.debug,
            filter: this.filter.bind(this),
            followRelations: this.props.followRelations,
        };
    }
}

export const fieldSelectorField = {
    component: FieldSelectorField,
    displayName: _t("Field Selector"),
    supportedTypes: ["char"],
    supportedOptions: [
        {
            label: _t("Follow relations"),
            name: "follow_relations",
            type: "boolean",
            default: true,
        },
        {
            label: _t("Model"),
            name: "model",
            type: "string",
        },
        {
            label: _t("Only searchable"),
            name: "only_searchable",
            type: "string",
        },
    ],
    extractProps({ options }, dynamicInfo) {
        return {
            allowProperties: options.allow_properties ?? true,
            followRelations: options.follow_relations ?? true,
            onlySearchable: exprToBoolean(options.only_searchable),
            resModel: options.model,
        };
    },
};

registerField("field_selector", fieldSelectorField);
