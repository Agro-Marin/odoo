/** @odoo-module native */
import { registry } from "@web/core/registry";

import { listView } from "@web/views/list";
import { DocumentsControlPanel } from "../search/documents_control_panel.js";
import { DocumentsListController } from "./documents_list_controller.js";
import { DocumentsListModel } from "./documents_list_model.js";
import { DocumentsSecondaryListRenderer, DocumentsListRenderer } from "./documents_list_renderer.js";
import { DocumentsSearchModel } from "../search/documents_search_model.js";
import { DocumentsSearchPanel } from "../search/documents_search_panel.js";

export const DocumentsListView = Object.assign({}, listView, {
    SearchModel: DocumentsSearchModel,
    SearchPanel: DocumentsSearchPanel,
    ControlPanel: DocumentsControlPanel,
    Controller: DocumentsListController,
    Model: DocumentsListModel,
    Renderer: DocumentsListRenderer,
    searchMenuTypes: ["filter", "groupBy", "favorite"],
});

registry.category("views").add("documents_list", DocumentsListView);

export const DocumentsListViewSecondary = Object.assign({}, DocumentsListView, {
    Renderer: DocumentsSecondaryListRenderer,
});

registry.category("views").add("documents_list_secondary", DocumentsListViewSecondary);
