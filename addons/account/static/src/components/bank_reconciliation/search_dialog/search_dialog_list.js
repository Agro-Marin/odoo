/** @odoo-module native */
import { useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ListController, ListRenderer, listView } from "@web/views/list";

export class BankRecReconcileDialogListController extends ListController {
    static template = "account.BankRecReconcileDialogListView";
    static props = {
        ...ListController.props,
        bankRecInfo: { type: Object, optional: true },
    };

    async onSelectionChanged() {
        this.props.bankRecInfo.onSelectionChanged(this);
    }
}

export class BankRecReconcileDialogListRenderer extends ListRenderer {
    static template = "account.BankRecReconcileDialogListRenderer";
    static recordRowTemplate = "account.BankRecReconcileDialogListRenderer.RecordRow";
    static props = [...ListRenderer.props, "bankRecInfo?"];

    setup() {
        super.setup();
        if (this.props.bankRecInfo?.state) {
            this.bankRecState = useState(this.props.bankRecInfo.state);
        }
    }

    /** @override */
    buildRowApi() {
        return {
            ...super.buildRowApi(),
            openMoveView: (record) => this.openMoveView(this.resolveRowRecord(record)),
        };
    }

    async openMoveView(record) {
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: record.data.move_id.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

export const bankRecReconcileDialogListRenderer = {
    ...listView,
    Renderer: BankRecReconcileDialogListRenderer,
    Controller: BankRecReconcileDialogListController,
    props: (genericProps, view) => {
        const baseProps = listView.props(genericProps, view);
        return {
            ...baseProps,
            bankRecInfo: genericProps.bankRecInfo,
        };
    },
};

registry
    .category("views")
    .add("bank_rec_dialog_list", bankRecReconcileDialogListRenderer);
