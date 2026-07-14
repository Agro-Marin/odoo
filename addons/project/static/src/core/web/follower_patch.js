/** @odoo-module native */
import { Follower } from "@mail/core/web/follower";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(Follower.prototype, {
    /**
     * Removing a follower who is a project collaborator also revokes their
     * portal access to the project (server-side unsubscribe logic), so ask
     * for confirmation first.
     */
    async onClickRemove() {
        const follower = this.props.follower;
        if (follower.partner_id.in(follower.thread.collaborator_ids)) {
            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Remove Collaborator"),
                body: _t(
                    "This follower is currently a project collaborator. Removing them will revoke their portal access to the project. Are you sure you want to proceed?"
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
