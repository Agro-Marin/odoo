/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { deleteConfirmationMessage } from "@web/ui/dialog/confirmation_dialog";

import { showAccountUploadButton } from "../account_file_uploader_mixin.js";
import { AccountUploadListController } from "../account_upload_list/account_upload_list_controller.js";

export class AccountMoveListController extends AccountUploadListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.account_move_service = useService("account_move");
        this.showUploadButton = showAccountUploadButton(this.props.context);
    }

    get actionMenuProps() {
        const actionMenuProps = {
            ...super.actionMenuProps,
            printDropdownTitle: _t("Print"),
        };
        if (this.props.resModel === "account.move") {
            actionMenuProps.loadExtraPrintItems = this.loadExtraPrintItems.bind(this);
        }
        return actionMenuProps;
    }

    async loadExtraPrintItems() {
        const selectedResIds = await this.model.root.getResIds(true);
        return this.orm.call("account.move", "get_extra_print_items", [selectedResIds]);
    }

    async onDeleteSelectedRecords() {
        const deleteConfirmationDialogProps = this.deleteConfirmationDialogProps;
        const selectedResIds = await this.model.root.getResIds(true);
        let body = deleteConfirmationMessage;
        if (this.model.root.isDomainSelected || this.model.root.selection.length > 1) {
            body = _t("Are you sure you want to delete these records?");
        }
        deleteConfirmationDialogProps.body =
            await this.account_move_service.getDeletionDialogBody(body, selectedResIds);
        this.deleteRecordsWithConfirmation(deleteConfirmationDialogProps);
    }
}
