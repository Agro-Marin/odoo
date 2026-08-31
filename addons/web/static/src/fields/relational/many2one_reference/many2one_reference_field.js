// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { stableM2OValue } from "@web/fields/relational/many2one/many2one";
import {
    extractM2OFieldProps,
    m2oSupportedAttributes,
    m2oSupportedOptions,
    Many2OneField,
} from "@web/fields/relational/many2one/many2one_field";
import { getFieldDomain } from "@web/model/relational_model";

export class Many2OneReferenceField extends Many2OneField {
    static template = "web.Many2OneReferenceField";

    setup() {
        this.updateValue = this.update.bind(this);
        this.selfExcludingDomain = () => {
            const { record, name, domain } = this.props;
            return Domain.and([
                new Domain(getFieldDomain(record, name, domain)),
                new Domain([["id", "!=", record.resId]]),
            ]).toList();
        };
    }

    /** @returns {Object} */
    get m2oProps() {
        const relation = this.relation;
        const value = this.field.value;
        /** @type {Record<string, any>} */
        const props = {
            ...super.m2oProps,
            relation,
            value: stableM2OValue(
                this.props,
                value && { id: value.resId, display_name: value.displayName },
            ),
            readonly: this.props.readonly || !relation,
            update: this.updateValue,
        };
        const { resId, resModel } = this.props.record;
        if (resModel === "ir.attachment" && relation === "ir.attachment" && resId) {
            props.domain = this.selfExcludingDomain;
        }
        return props;
    }

    /** @returns {string|false} */
    get relation() {
        const modelField = this.field.definition.model_field;
        if (!(modelField in this.props.record.data)) {
            throw new Error(
                `Many2OneReferenceField: model_field must be in view (${modelField})`,
            );
        }
        return this.props.record.data[modelField];
    }

    /** @param {{ id: number, display_name: string }|false} record */
    update(record) {
        const nextVal = record && {
            resId: record.id,
            displayName: record.display_name,
        };
        return this.field.update(nextVal);
    }
}

registerField("many2one_reference", {
    component: Many2OneReferenceField,
    displayName: _t("Many2OneReference"),
    supportedOptions: m2oSupportedOptions,
    supportedAttributes: m2oSupportedAttributes,
    extractProps(staticInfo, dynamicInfo) {
        return extractM2OFieldProps(staticInfo, dynamicInfo);
    },
    relatedFields: [{ name: "display_name", type: "char" }],
    supportedTypes: ["many2one_reference"],
});
