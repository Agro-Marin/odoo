/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/fields/relational/many2many_tags";

export class Many2ManyPackageTagsField extends Many2ManyTagsField {
    get hasNoneTag() {
        return this.props.record.data?.has_lines_without_result_package || false;
    }

    get tags() {
        const tags = super.tags;
        if (this.hasNoneTag) {
            const records = this.props.record.data[this.props.name].records;
            const lastRecord = records.at(-1);
            if (lastRecord) {
                tags.push({
                    ...this.getTagProps(lastRecord),
                    id: "datapoint_None",
                    text: _t("No Package"),
                    resId: false,
                    onDelete: undefined,
                });
            }
        }
        return tags;
    }

    getTagProps(record) {
        return {
            ...super.getTagProps(record),
            text: record.data.name,
        };
    }
}

export const many2ManyPackageTagsField = {
    ...many2ManyTagsField,
    component: Many2ManyPackageTagsField,
    additionalClasses: ["o_field_many2many_tags"],
    relatedFields: () => [{ name: "name", type: "char" }],
};

registry.category("fields").add("package_m2m", many2ManyPackageTagsField);
