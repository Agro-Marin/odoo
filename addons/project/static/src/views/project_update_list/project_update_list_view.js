/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ProjectUpdateListController } from './project_update_list_controller.js';
import { ProjectRelationalModel } from "../project_relational_model.js";

export const projectUpdateListView = {
    ...listView,
    Controller: ProjectUpdateListController,
    Model: ProjectRelationalModel,
};

registry.category('views').add('project_update_list', projectUpdateListView);
