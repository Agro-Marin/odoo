/** @odoo-module native */
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/fields/relational/many2many_tags/many2many_tags_field";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";


export class Many2ManyPackageTagsField extends Many2ManyTagsField {
    // Getter, not a setup() snapshot: has_lines_without_result_package is a
    // computed field that changes as move lines change, so the "No Package" tag
    // must re-evaluate on every render.
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
                    // Synthetic tag: never let it inherit a real package's identity
                    // or delete handler (would target the wrong record if this field
                    // ever becomes editable).
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
    additionalClasses: ['o_field_many2many_tags'],
    relatedFields: () => [
        { name: "name", type: "char" },
    ],
}

registry.category("fields").add("package_m2m", many2ManyPackageTagsField);
