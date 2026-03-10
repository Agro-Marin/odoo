/** @odoo-module */
import { registry } from "@web/core/registry";
import { fileUploadListView } from "../file_upload_list/file_upload_list_view.js";
import { AccountMoveListController } from "./account_move_list_controller.js";
import { AccountMoveListRenderer } from "./account_move_list_renderer.js";

export const accountMoveUploadListView = {
    ...fileUploadListView,
    Controller: AccountMoveListController,
    Renderer: AccountMoveListRenderer,
    buttonTemplate: "account.AccountMoveListView.Buttons",
};

registry.category("views").add("account_tree", accountMoveUploadListView);
