/** @odoo-module native */
import { registry } from "@web/core/registry";

import { kanbanView } from "@web/views/kanban";
import { DocumentsControlPanel } from "../search/documents_control_panel.js";
import { DocumentsKanbanController } from "./documents_kanban_controller.js";
import { DocumentsKanbanModel } from "./documents_kanban_model.js";
import { DocumentsKanbanRenderer } from "./documents_kanban_renderer.js";
import { DocumentsSearchModel } from "../search/documents_search_model.js";
import { DocumentsSearchPanel } from "../search/documents_search_panel.js";
import { DocumentsKanbanArchParser } from "./documents_kanban_arch_parser.js";
import { DocumentsKanbanCompiler } from "./documents_kanban_compiler.js";


export const DocumentsKanbanView = Object.assign({}, kanbanView, {
    ArchParser: DocumentsKanbanArchParser,
    SearchModel: DocumentsSearchModel,
    SearchPanel: DocumentsSearchPanel,
    ControlPanel: DocumentsControlPanel,
    Controller: DocumentsKanbanController,
    Compiler: DocumentsKanbanCompiler,
    Model: DocumentsKanbanModel,
    Renderer: DocumentsKanbanRenderer,
    searchMenuTypes: ["filter", "groupBy", "favorite"],
});

registry.category("views").add("documents_kanban", DocumentsKanbanView);
