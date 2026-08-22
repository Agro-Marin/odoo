/** @odoo-module native */
import { markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

export class AccountMoveService {
    constructor(env, services) {
        this.setup(env, services);
    }

    setup(env, services) {
        this.env = env;
        this.action = services.action;
        this.dialog = services.dialog;
        this.orm = services.orm;
    }

    async getDeletionDialogBody(body, moveIds) {
        const isMoveEndOfChain = await this.orm.call(
            "account.move",
            "check_move_sequence_chain",
            [moveIds],
        );
        if (!isMoveEndOfChain) {
            const message = _t("This operation will create a gap in the sequence.");
            return markup`<div class="text-danger">${message}</div>${body}`;
        }
        return body;
    }

    async downloadPdf(accountMoveId, target = "download") {
        const downloadAction = await this.orm.call(
            "account.move",
            "action_invoice_download_pdf",
            [accountMoveId, target],
        );
        await this.action.doAction(downloadAction);
    }

    /**
     * Open the business document a record stands for: the payment, bank
     * transaction or entry its own `action_view_business_doc` resolves to.
     *
     * Through `doActionButton`, so the call carries the button protocol — the
     * context, and an `onClose` the caller can refresh from. Five widgets used to
     * name the method themselves, three of them with a bare `orm.call` that got
     * neither; one of the five was already spelling it the old way (§0.2).
     *
     * @param {{resModel: string, resId: number, context?: Object,
     *          onClose?: Function}} params
     */
    openBusinessDoc({ resModel, resId, context, onClose }) {
        return this.action.doActionButton({
            type: "object",
            name: "action_view_business_doc",
            resModel,
            resId,
            context,
            onClose,
        });
    }
}

export const accountMoveService = {
    dependencies: ["action", "dialog", "orm"],
    start(env, services) {
        return new AccountMoveService(env, services);
    },
};

registry.category("services").add("account_move", accountMoveService);
