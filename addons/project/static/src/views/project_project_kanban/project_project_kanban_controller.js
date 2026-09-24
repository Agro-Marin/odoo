/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { KanbanController } from "@web/views/kanban";

import { ProjectTemplateDropdown } from "../components/project_template_dropdown.js";

export class ProjectKanbanController extends KanbanController {
    static template = "project.ProjectKanbanView";
    static components = {
        ...KanbanController.components,
        ProjectTemplateDropdown,
    };

    setup() {
        super.setup();
        this.ui = useService("ui");
        onWillStart(async () => {
            this.isProjectManager = await user.hasGroup(
                "project.group_project_manager",
            );
        });
    }

    getStaticActionMenuItems() {
        const actionMenuItems = super.getStaticActionMenuItems(...arguments);
        if (!this.isProjectManager) {
            ["duplicate", "archive", "unarchive"].forEach(
                (item) => delete actionMenuItems[item],
            );
        }
        return actionMenuItems;
    }
}
