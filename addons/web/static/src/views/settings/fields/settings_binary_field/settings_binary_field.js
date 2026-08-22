// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";
import { BinaryField, binaryField } from "@web/fields/media/binary/binary_field";
export class SettingsBinaryField extends BinaryField {
    static template = "web.SettingsBinaryField";

    /**
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
