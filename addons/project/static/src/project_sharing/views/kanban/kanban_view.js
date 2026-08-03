/** @odoo-module native */
import { ProjectTaskControlPanel } from "@project/views/project_task_control_panel/project_task_control_panel";
import { ProjectTaskRelationalModel } from "@project/views/project_task_relational_model";
import { kanbanView } from "@web/views/kanban";

export class ProjectSharingTaskKanbanModel extends ProjectTaskRelationalModel {
    async _webReadGroup(config) {
        config.context = {
            ...config.context,
            project_kanban: true,
        };
        return super._webReadGroup(...arguments);
    }
}

kanbanView.ControlPanel = ProjectTaskControlPanel;
kanbanView.Model = ProjectSharingTaskKanbanModel;
