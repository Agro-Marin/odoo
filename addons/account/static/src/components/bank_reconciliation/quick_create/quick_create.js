/** @odoo-module native */
import {
    KanbanQuickCreateController,
    KanbanRecordQuickCreate,
} from "@web/views/kanban";

export class BankRecQuickCreateController extends KanbanQuickCreateController {
    static template = "account.BankRecQuickCreateController";

    showFormDialogInError(e) {
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
