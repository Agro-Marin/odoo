/** @odoo-module native */
import { registry } from "@web/core/registry";

import { listView } from "@web/views/list";
import { DocumentsControlPanel } from "../search/document_control_panel.js";
import { DocumentsListController } from "./document_list_controller.js";
import { DocumentsListModel } from "./document_list_model.js";
import {
    DocumentsSecondaryListRenderer,
    DocumentsListRenderer,
} from "./document_list_renderer.js";
import { DocumentsSearchModel } from "../search/document_search_model.js";
import { DocumentsSearchPanel } from "../search/document_search_panel.js";

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
