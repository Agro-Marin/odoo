/** @odoo-module native */
import { RecipientsInputTagsList } from "@mail/core/web/recipients_input_tags_list";
import { RecipientsPopover } from "@mail/core/web/recipients_popover";
import { parseEmail } from "@mail/utils/common/format";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/fields/relational/many2many_tags";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";
import { usePopover } from "@web/ui/popover";
/**
 * @typedef {import("@web/model/relational_model/record").RelationalRecord} RelationalRecord
 */
export class FieldMany2ManyTagsEmailTagsList extends RecipientsInputTagsList {
    static template = "FieldMany2ManyTagsEmailTagsList";
}

export class FieldMany2ManyTagsEmailMany2xAutocomplete extends Many2XAutocomplete {
    /**
     * @param {string} value
     * @returns {Object}
     */
    getCreationContext(value) {
        const [name, email] = value ? parseEmail(value) : ["", ""];
        const context = /** @type {Object<string, any>} */ (
            super.getCreationContext(name)
        );
        if (email) {
            context["default_email"] = email;
        }
        return context;
    }
}

export class FieldMany2ManyTagsEmail extends Many2ManyTagsField {
    static template = "FieldMany2ManyTagsEmailTags";
    static components = {
        ...Many2ManyTagsField.components,
        TagsList: FieldMany2ManyTagsEmailTagsList,
        Many2XAutocomplete: FieldMany2ManyTagsEmailMany2xAutocomplete,
    };
    static props = {
        ...Many2ManyTagsField.props,
        context: { type: Object, optional: true },
        canEditTags: { type: Boolean, optional: true },
    };

    setup() {
        super.setup();
        if (this.quickCreate) {
            this.quickCreate = this.quickCreateRecipient.bind(this);
        }
        this.recipientsPopover = usePopover(RecipientsPopover);
        this.actionService = useService("action");
    }

    get tags() {
        const tags = super.tags;
        const emailByResId = this.props.record.data[this.props.name].records.reduce(
            /**
             * @param {Object<number, string>} acc
             * @param {RelationalRecord} record
             */
            (acc, record) => {
                acc[record.resId] = record.data.email;
                return acc;
            },
            /** @type {Object<number, string>} */ ({}),
        );
        tags.forEach((/** @type {Object<string, any>} */ tag) => {
            tag.email = emailByResId[tag.resId];
            tag.name = tag.text;
            tag.title = tag.text;
        });
        return tags;
    }

    /**
     * @param {RelationalRecord} record
     * @returns {Object}
     */
    getTagProps(record) {
        return {
            ...super.getTagProps(record),
            text:
                record.data.name ||
                record.data.email ||
                record.data.display_name ||
                _t("Unnamed"),
            /** @param {MouseEvent} ev */
            onClick: (ev) => this.onTagClick(ev, record),
        };
    }

    /**
     * @param {MouseEvent} event
     * @param {RelationalRecord} record
     */
    onTagClick(event, record) {
        const viewProfileBtnOverride = () => {
            const action = {
                type: "ir.actions.act_window",
                res_model: "res.partner",
                res_id: record.resId,
                views: [[false, "form"]],
                target: "current",
            };
            this.actionService.doAction(action);
        };
        this.recipientsPopover.open(/** @type {HTMLElement} */ (event.target), {
            id: record.resId,
            viewProfileBtnOverride,
        });
    }

    /**
     * @param {string} request
     * @returns {Promise<any>}
     */
    async quickCreateRecipient(request) {
        const [name, email] = parseEmail(request);
        const [partnerId] = await this.orm.create("res.partner", [{ name, email }]);
        return this.props.record.data[this.props.name].addAndRemove({
            add: [partnerId],
        });
    }

    /**
     * @param {string} newEmail
     * @param {number} partnerId
     * @returns {Promise<any>}
     */
    async updateRecipient(newEmail, partnerId) {
        const list = this.props.record.data[this.props.name];
        const partnerRecord = list.records.find(
            /** @param {RelationalRecord} r */ (r) => r.resId === partnerId,
        );
        partnerRecord.canSaveOnUpdate = true;
        return partnerRecord.update({ email: newEmail }, { save: true });
    }
}

export const fieldMany2ManyTagsEmail = {
    ...many2ManyTagsField,
    component: FieldMany2ManyTagsEmail,
    supportedOptions: [
        ...many2ManyTagsField.supportedOptions,
        {
            label: _t("Edit Tags"),
            name: "edit_tags",
            type: "boolean",
        },
    ],
    /**
     * @param {Object} fieldInfo
     * @param {Object} fieldInfo.options
     * @param {Object} fieldInfo.attrs
     * @param {Object} dynamicInfo
     * @returns {Object}
     */
    extractProps({ options, attrs }, dynamicInfo) {
        const props = many2ManyTagsField.extractProps(...arguments);
        props.context = dynamicInfo.context;
        const hasEditPermission = attrs.can_write
            ? evaluateBooleanExpr(attrs.can_write)
            : true;
        props.canEditTags = options.edit_tags ? hasEditPermission : false;
        return props;
    },
    /**
     * @param {{attrs: Object, options: Object, viewType?: string}} fieldInfo
     * @returns {Object[]}
     */
    relatedFields: (fieldInfo) => [
        ...many2ManyTagsField.relatedFields(fieldInfo),
        { name: "email", type: "char", readonly: false },
        { name: "name", type: "char" },
    ],
    additionalClasses: ["o_field_many2many_tags"],
};

registry.category("fields").add("many2many_tags_email", fieldMany2ManyTagsEmail);
