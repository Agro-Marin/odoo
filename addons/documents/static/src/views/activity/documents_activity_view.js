/** @odoo-module native */
import { registry } from "@web/core/registry";

import { activityView } from "@mail/views/web/activity/activity_view";
import { DocumentsActivityController } from "./documents_activity_controller.js";
import { DocumentsActivityModel } from "./documents_activity_model.js";
import { DocumentsActivityRenderer } from "./documents_activity_renderer.js";
import { DocumentsControlPanel } from "../search/documents_control_panel.js";
import { DocumentsSearchModel } from "../search/documents_search_model.js";

export const DocumentsActivityView = {
    ...activityView,
    ControlPanel: DocumentsControlPanel,
    Controller: DocumentsActivityController,
    Model: DocumentsActivityModel,
    Renderer: DocumentsActivityRenderer,
    SearchModel: DocumentsSearchModel,
};
registry.category("views").add("documents_activity", DocumentsActivityView);
