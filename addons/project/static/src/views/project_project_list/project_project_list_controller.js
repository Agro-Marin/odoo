/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";
import { ListController } from "@web/views/list";

import { ProjectTemplateDropdown } from "../components/project_template_dropdown.js";

export class ProjectListController extends ListController {
    static template = "project.ProjectListView";
    static components = {
        ...ListController.components,
        ProjectTemplateDropdown,
    };

    setup() {
        super.setup();
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
