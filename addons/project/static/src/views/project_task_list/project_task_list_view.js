/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list";

import { HighlightProjectTaskSearchModel } from "../highlight_project_task_search_model.js";
import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskRelationalModel } from "../project_task_relational_model.js";
import { ProjectTaskListController } from "./project_task_list_controller.js";
import { ProjectTaskListRenderer } from "./project_task_list_renderer.js";

export const projectTaskListView = {
    SearchModel: HighlightProjectTaskSearchModel,
    ...listView,
    ControlPanel: ProjectTaskControlPanel,
    Controller: ProjectTaskListController,
    Model: ProjectTaskRelationalModel,
    Renderer: ProjectTaskListRenderer,
};

registry.category("views").add("project_task_list", projectTaskListView);
