/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { KanbanController } from "@web/views/kanban";

import { ProjectRightSidePanel } from "../../components/project_right_side_panel/project_right_side_panel.js";

export class ProjectUpdateKanbanController extends KanbanController {
    static template = "project.ProjectUpdateKanbanView";
    static components = {
        ...KanbanController.components,
        ProjectRightSidePanel,
    };
    setup() {
        super.setup();
        this.ui = useService("ui");
    }

    get className() {
        return super.className + " o_controller_with_rightpanel";
    }
}
