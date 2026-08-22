/** @odoo-module native */
import { onMounted } from "@odoo/owl";
import { TagsList } from "@web/components/tags_list";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import {
    Many2ManyTagsFieldColorEditable,
    many2ManyTagsFieldColorEditable,
} from "@web/fields/relational/many2many_tags";

export class FieldMany2ManyTagsBanksTagsList extends TagsList {
    static template = "FieldMany2ManyTagsBanksTagsList";
}

export class FieldMany2ManyTagsBanks extends Many2ManyTagsFieldColorEditable {
    static template = "account.FieldMany2ManyTagsBanks";
    static components = {
        ...Many2ManyTagsFieldColorEditable.components,
        TagsList: FieldMany2ManyTagsBanksTagsList,
    };

    setup() {
        super.setup();
        this.actionService = useService("action");
        onMounted(async () => {
            const isDirty = await this.props.record.model.root.isDirty();
            if (isDirty) {
                this.props.record.model.root.save();
            }
        });
    }

    getTagProps(record) {
        return {
            ...super.getTagProps(record),
            allowOutPayment: record.data?.allow_out_payment,
        };
    }

    openBanksListView() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("Banks"),
            res_model: this.relation,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: this.getDomain(),
            target: "current",
        });
    }
}

export const fieldMany2ManyTagsBanks = {
    ...many2ManyTagsFieldColorEditable,
    component: FieldMany2ManyTagsBanks,
    supportedOptions: [
        ...(many2ManyTagsFieldColorEditable.supportedOptions || []),
        {
            label: _t("Allows out payments"),
            name: "allow_out_payment_field",
            type: "boolean",
        },
    ],
    additionalClasses: [
        ...(many2ManyTagsFieldColorEditable.additionalClasses || []),
        "o_field_many2many_tags",
    ],
    relatedFields: ({ options }) => [
        ...many2ManyTagsFieldColorEditable.relatedFields({ options }),
        ...(options.allow_out_payment_field
            ? [
                  {
                      name: options.allow_out_payment_field,
                      type: "boolean",
                      readonly: false,
                  },
              ]
            : []),
    ],
};

registry.category("fields").add("many2many_tags_banks", fieldMany2ManyTagsBanks);
