/** @odoo-module native */
import { SyncPopup } from "@point_of_sale/app/components/popups/sync_popup/sync_popup";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/ui/dialog";
import {
    alertDialogDefaultProps,
    alertDialogProps,
    confirmationDialogDefaultProps,
    confirmationDialogProps,
} from "@web/ui/dialog/confirmation_dialog";
const log = makeLogger("pos.dialog.confirmation");
patch(ConfirmationDialog.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
    },
    async cancel() {
        this.props.getPayload && this.props.getPayload(false);
        return this.execButton(this.props.cancel);
    },
    async confirm() {
        this.props.getPayload && this.props.getPayload(true);
        return this.execButton(this.props.confirm);
    },
    async dismiss() {
        this.props.getPayload && this.props.getPayload(false);
        return this.execButton(this.props.dismiss || this.props.cancel);
    },
    async _reloadData() {
        this.props.close();
        if (this.pos.config?.module_pos_restaurant) {
            try {
                log.pipeline("reloadData: sync before reload");
                await this.pos.syncAllOrders();
            } catch (error) {
                logPosMessage(
                    "ConfirmationDialog",
                    "_reloadData",
                    "Failed to sync orders",
                    undefined,
                    [error],
                );
            }
        }
        this.pos.dialog.add(SyncPopup, {
            title: _t("Reload Data"),
            confirm: (fullReload) => this.pos.reloadData(fullReload),
        });
    },
});

Object.assign(confirmationDialogProps, {
    getPayload: { type: Function, optional: true },
    showReloadButton: { type: Boolean, optional: true },
});

Object.assign(confirmationDialogDefaultProps, {
    showReloadButton: false,
});

Object.assign(alertDialogProps, {
    getPayload: { type: Function, optional: true },
    showReloadButton: { type: Boolean, optional: true },
});

Object.assign(alertDialogDefaultProps, {
    showReloadButton: false,
});
