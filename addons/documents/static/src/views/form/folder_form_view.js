/** @odoo-module native */
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form";
import { FolderFormController } from "./folder_form_controller.js";

export const FolderFormView = {
    ...formView,
    Controller: FolderFormController,
};

registry.category("views").add("folder_form", FolderFormView);
