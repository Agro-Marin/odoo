/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { useDialogContext } from "@web/core/dialog_context_hooks";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
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
        this.dialogContext = useDialogContext();
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
