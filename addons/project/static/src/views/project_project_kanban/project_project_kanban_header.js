/** @odoo-module */
import { KanbanHeader } from "@web/views/kanban/kanban_header";
import { ProjectProjectGroupConfigMenu } from "./project_project_group_config_menu.js";

export class ProjectProjectKanbanHeader extends KanbanHeader {
    static components = {
        ...KanbanHeader.components,
        GroupConfigMenu: ProjectProjectGroupConfigMenu,
    };
}
