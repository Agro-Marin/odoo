/** @odoo-module */
import { registry } from "@web/core/registry";
import { listView } from '@web/views/list/list_view';
import { ProjectTaskListController } from "./project_task_list_controller.js";
import { ProjectTaskListRenderer } from "./project_task_list_renderer.js";
import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskRelationalModel } from "../project_task_relational_model.js";

export const projectTaskListView = {
    ...listView,
    ControlPanel: ProjectTaskControlPanel,
    Controller: ProjectTaskListController,
    Model: ProjectTaskRelationalModel,
    Renderer: ProjectTaskListRenderer,
};

registry.category("views").add("project_task_list", projectTaskListView);
