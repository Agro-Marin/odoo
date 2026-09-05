/** @odoo-module native */
import { registry } from "@web/core/registry";

import { activityView } from "@mail/views/web/activity/activity_view";
import { DocumentsActivityController } from "./document_activity_controller.js";
import { DocumentsActivityModel } from "./document_activity_model.js";
import { DocumentsActivityRenderer } from "./document_activity_renderer.js";
import { DocumentsControlPanel } from "../search/document_control_panel.js";
import { DocumentsSearchModel } from "../search/document_search_model.js";

export const DocumentsActivityView = {
    ...activityView,
    ControlPanel: DocumentsControlPanel,
    Controller: DocumentsActivityController,
    Model: DocumentsActivityModel,
    Renderer: DocumentsActivityRenderer,
    SearchModel: DocumentsSearchModel,
};
registry.category("views").add("documents_activity", DocumentsActivityView);
