/** @odoo-module native */
import { TagsList } from "@web/components/tags_list";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many";

import { useSkillsRecordOpener } from "../use_skills_record_opener.js";

export class One2ManyTagsSkillsField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        TagsList,
    };
    static template = "hr_skills.One2ManyTagsSkillsField";

    setup() {
        super.setup();
        useSkillsRecordOpener(this, () => _t("Select Skills"));
    }

    getTagProps(record) {
        const tagProps = {
            id: record.id,
            resId: record.resId,
            text: record.data.display_name,
            colorIndex: record.data.color,
            canEdit: true,
            onClick: (ev) => this.onTagClick(ev, record),
            onDelete: !this.props.readonly
                ? () => this.activeActions.onDelete(record)
                : undefined,
        };
        return tagProps;
    }

    get tags() {
        return this.props.record.data[this.props.name].records.map((record) =>
            this.getTagProps(record),
        );
    }

    onTagClick(ev, record) {
        this.openRecord(record);
    }
}

export const one2ManyTagsSkillsField = {
    ...x2ManyField,
    component: One2ManyTagsSkillsField,
};

registry.category("fields").add("many2one_tags_skills", one2ManyTagsSkillsField);
