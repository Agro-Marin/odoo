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
        const record = this.props.record;
        if (
            !name ||
            !record?.resModel ||
            !this.env.approvalGatedModels?.[record.resModel]
        ) {
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
        if (kind === "action") {
            // A window action has nothing on the server to refuse it, so the browser
            // asks first; an object button is gated where it runs.
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
                            return this.approvalGate.check();
                        },
                    }),
            });
        }
    },
});

ViewButton.components = { ...ViewButton.components, ApprovalButton };
