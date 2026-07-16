/** @odoo-module native */
import { registry } from "@web/core/registry";

import { AccountUploadListRenderer } from "../account_upload_list/account_upload_list_renderer.js";
import { fileUploadListView } from "../file_upload_list/file_upload_list_view.js";
import { AccountMoveListController } from "./account_move_list_controller.js";

export const accountMoveUploadListView = {
    ...fileUploadListView,
    Controller: AccountMoveListController,
    Renderer: AccountUploadListRenderer,
    buttonTemplate: "account.AccountMoveListView.Buttons",
};

registry.category("views").add("account_tree", accountMoveUploadListView);
