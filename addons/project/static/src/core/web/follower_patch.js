/** @odoo-module native */
import { Follower } from "@mail/core/web/follower";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/ui/dialog";

patch(Follower.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialogService = useService("dialog");
    },

    async onClickRemove() {
        const follower = this.props.follower;
        if (follower.partner_id.in(follower.thread.collaborator_ids)) {
            this.dialogService.add(ConfirmationDialog, {
                title: _t("Remove Collaborator"),
                body: _t(
                    "This follower is currently a project collaborator. Removing them will revoke their portal access to the project. Are you sure you want to proceed?",
                ),
                confirmLabel: _t("Remove Collaborator"),
                cancelLabel: _t("Discard"),
                confirm: () => super.onClickRemove(),
                cancel: () => {},
            });
        } else {
            return super.onClickRemove();
        }
    },
});
