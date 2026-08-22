/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/fields/standard_field_props";

class X2ManyButtons extends Component {
    static template = "account.X2ManyButtons";
    static props = {
        ...standardFieldProps,
        treeLabel: { type: String },
        nbRecordsShown: { type: Number, optional: true },
    };

    setup() {
        this.action = useService("action");
        this.accountMove = useService("account_move");
    }

    async openTreeAndDiscard() {
        const ids = this.currentField.currentIds;
        await this.props.record.discard();
        const context =
            this.currentField.resModel === "account.move"
                ? { list_view_ref: "account.view_duplicated_moves_tree_js" }
                : {};
        this.action.doAction({
            name: this.props.treeLabel,
            type: "ir.actions.act_window",
            res_model: this.currentField.resModel,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["id", "in", ids]],
            context: context,
        });
    }

    async openFormAndDiscard(id) {
        const resModel = this.currentField.resModel;
        await this.props.record.discard();
        return this.accountMove.openBusinessDoc({ resModel, resId: id });
    }

    get currentField() {
        return this.props.record.data[this.props.name];
    }
}

registry.category("fields").add("x2many_buttons", {
    component: X2ManyButtons,
    relatedFields: [{ name: "display_name", type: "char" }],
    extractProps: ({ attrs, string }) => ({
        treeLabel: string || _t("Records"),
        nbRecordsShown: attrs.nb_records_shown ? parseInt(attrs.nb_records_shown) : 3,
    }),
});
