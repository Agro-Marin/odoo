/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list";

import { ProjectRelationalModel } from "../project_relational_model.js";
import { ProjectListController } from "./project_project_list_controller.js";
import { ProjectProjectListRenderer } from "./project_project_list_renderer.js";

export const projectProjectListView = {
    ...listView,
    Renderer: ProjectProjectListRenderer,
    Controller: ProjectListController,
    Model: ProjectRelationalModel,
};

registry.category("views").add("project_project_list", projectProjectListView);
