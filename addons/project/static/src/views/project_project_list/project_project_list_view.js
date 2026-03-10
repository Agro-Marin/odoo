/** @odoo-module */
import { registry } from "@web/core/registry";
import { listView } from '@web/views/list/list_view';
import { ProjectProjectListRenderer } from "./project_project_list_renderer.js";
import { ProjectListController } from "./project_project_list_controller.js";
import { ProjectRelationalModel } from "../project_relational_model.js";

export const projectProjectListView = {
    ...listView,
    Renderer: ProjectProjectListRenderer,
    Controller: ProjectListController,
    Model: ProjectRelationalModel,
};

registry.category("views").add("project_project_list", projectProjectListView);
