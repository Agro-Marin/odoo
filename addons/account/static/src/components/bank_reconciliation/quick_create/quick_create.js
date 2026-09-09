/** @odoo-module native */
import {
    KanbanRecordQuickCreate,
    KanbanQuickCreateController,
} from "@web/views/kanban";

export class BankRecQuickCreateController extends KanbanQuickCreateController {
    static template = "account.BankRecQuickCreateController";

    showFormDialogInError(e) {
        // Override because in the case of the bank rec widget, we do not want the bank statement line form view to be
        // opened when an error occurs. Instead, we close the quick create and display the error.
        this.props.onCancel();
        throw e;
    }
}

export class BankRecQuickCreate extends KanbanRecordQuickCreate {
    static template = "account.BankRecQuickCreate";
    static props = {
        ...KanbanRecordQuickCreate.props,
        resModel: { type: String },
        context: { type: Object },
        group: { type: Object, optional: true },
    };
    static components = { BankRecQuickCreateController };

    async getQuickCreateProps(props) {
        await super.getQuickCreateProps({
            ...props,
            group: {
                resModel: props.resModel,
                context: props.context,
            },
        });
    }
}
