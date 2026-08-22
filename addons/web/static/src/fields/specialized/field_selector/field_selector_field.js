// @ts-check
/** @odoo-module native */

import { ModelFieldSelector } from "@web/components/model_field_selector/model_field_selector";
import { formatChar } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class FieldSelectorField extends FieldComponent {
    static template = "web.FieldSelectorField";
    static components = { ModelFieldSelector };
    static props = {
        ...standardFieldProps,
        resModel: { type: String, optional: true },
        onlySearchable: { type: Boolean, optional: true },
        allowProperties: { type: Boolean, optional: true },
        comodel: { type: String, optional: true },
        followRelations: { type: Boolean, optional: true },
        required: { type: Boolean, optional: true },
    };

    /** @param {Record<string, any>} fieldDef */
    filter(fieldDef) {
        if (fieldDef.type === "separator") {
            return false;
        }
        if (!this.props.allowProperties && fieldDef.type === "properties") {
            return false;
        }
        if (this.props.comodel && fieldDef.relation !== this.props.comodel) {
            // Relations stay: the wanted model may be several hops away, and
            // the chevron is the only way to get there. Everything else can
            // never be the field being asked for, so offering it is offering a
            // choice whose only outcome is a validation error later.
            if (!fieldDef.relation || !this.props.followRelations) {
                return false;
            }
        }
        return !this.props.onlySearchable || fieldDef.searchable;
    }

    /** @param {any} value */
    async update(value) {
        await this.field.update(value);
    }

    get formattedValue() {
        return formatChar(this.field.value);
    }

    get resModel() {
        const { record } = this.props;
        let resModel = this.props.resModel;
        if (record.fieldNames.includes(resModel)) {
            resModel = record.data[resModel];
        }
        return resModel || record.resModel;
    }

    get selectorProps() {
        return {
            allowEmpty: !this.props.required,
            path: this.field.value,
            resModel: this.resModel,
            readonly: this.props.readonly,
            update: this.update.bind(this),
            isDebugMode: !!this.env.debug,
            filter: this.filter.bind(this),
            followRelations: this.props.followRelations,
        };
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const fieldSelectorField = {
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
            label: _t("Comodel"),
            name: "comodel",
            type: "string",
            help: _t(
                "Only offer fields pointing at this model, and the relations reaching one.",
            ),
        },
        {
            label: _t("Only searchable"),
            name: "only_searchable",
            type: "string",
        },
        {
            label: _t("Allow properties"),
            name: "allow_properties",
            type: "boolean",
            default: true,
            help: _t("Let the selector descend into properties fields."),
        },
    ],
    extractProps({ options }, dynamicInfo) {
        return {
            allowProperties: options.allow_properties ?? true,
            comodel: options.comodel,
            followRelations: options.follow_relations ?? true,
            onlySearchable: exprToBoolean(options.only_searchable),
            resModel: options.model,
            required: dynamicInfo.required,
        };
    },
};

registerField("field_selector", fieldSelectorField);
