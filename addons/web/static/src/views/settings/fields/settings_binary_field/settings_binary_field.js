// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/fields/settings_binary_field/settings_binary_field - BinaryField variant resolving download URLs via the related field's relation */

import { registerField } from "@web/fields/_registry";
import { BinaryField, binaryField } from "@web/fields/media/binary/binary_field";
export class SettingsBinaryField extends BinaryField {
    static template = "web.SettingsBinaryField";

    /**
     * Resolve download URL data using the related field's relation model and ID.
     *
     * Only applies to the supported "m2o.binary" shape (e.g.
     * "company_id.logo"); anything else — no related, deeper chains, a
     * non-relational first hop, or an unset m2o on the settings
     * pseudo-record — falls back to the base binary download.
     *
     * @returns {{ model: string, field: string, id: number } & Record<string, any>}
     */
    getDownloadData() {
        const related = this.props.record.fields[this.props.name].related;
        const [fieldName, relatedFieldName, ...rest] = related?.split(".") || [];
        const relation = fieldName && this.props.record.fields[fieldName]?.relation;
        const relatedValue = fieldName && this.props.record.data[fieldName];
        if (!relatedFieldName || rest.length || !relation || !relatedValue?.id) {
            return super.getDownloadData();
        }
        return {
            ...super.getDownloadData(),
            model: relation,
            field: relatedFieldName,
            id: relatedValue.id,
        };
    }
}

const settingsBinaryField = {
    ...binaryField,
    component: SettingsBinaryField,
};

registerField({ name: "binary", view: "base_settings" }, settingsBinaryField);
