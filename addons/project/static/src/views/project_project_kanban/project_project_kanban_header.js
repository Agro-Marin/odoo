/** @odoo-module native */
import { KanbanHeader } from "@web/views/kanban";

import { ProjectProjectGroupConfigMenu } from "./project_project_group_config_menu.js";

export class ProjectProjectKanbanHeader extends KanbanHeader {
    static components = {
        ...KanbanHeader.components,
        GroupConfigMenu: ProjectProjectGroupConfigMenu,
    };
}
