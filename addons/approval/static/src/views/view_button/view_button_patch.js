/** @odoo-module native */
import { useSubEnv } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ViewButton } from "@web/views/view_button";

import { ApprovalButton } from "./approval_button";
import { useApprovalButton } from "./approval_button_hook";

patch(ViewButton.prototype, {
    setup() {
        super.setup(...arguments);
        const { name, type } = this.props.clickParams || {};
        if (!name || !this.props.record?.resModel || !this._isApprovalGated()) {
            return;
        }
        const kind = (type || "").replace(/=$/, "");
        if (kind !== "object" && kind !== "action") {
            return;
        }
        this.approvalGate = useApprovalButton({
            getRecord: () => this.props.record,
            method: kind === "object" && name,
            action: kind === "action" && name,
        });
        // A button stopped by its approvals warns and stays on the record, whatever
        // its kind. A window action has nothing on the server to refuse it, so it is
        // always asked; an object button is gated where it runs as well, so it is
        // asked only while its loaded approvals say it is gated.
        const onClickViewButton = this.env.onClickViewButton;
        useSubEnv({
            onClickViewButton: (params) =>
                onClickViewButton({
                    ...params,
                    beforeExecute: async () => {
                        if (
                            params.beforeExecute &&
                            (await params.beforeExecute()) === false
                        ) {
                            return false;
                        }
                        if (kind === "object" && !this.approvalGate.result?.gated) {
                            return true;
                        }
                        return this.approvalGate.check();
                    },
                }),
        });
    },

    /**
     * Whether this button's record belongs to a model with approval bindings. An
     * editor that draws every button's approvals, as Studio's does, overrides it.
     */
    _isApprovalGated() {
        return Boolean(this.env.approvalGatedModels?.[this.props.record.resModel]);
    },
});

ViewButton.components = { ...ViewButton.components, ApprovalButton };
