/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { user } from "@web/services/user";
import { useService } from "@web/core/utils/hooks";
import { GroupConfigMenu } from "@web/views/view_components/group_config_menu";

export class ProjectTaskGroupConfigMenu extends GroupConfigMenu {
    setup() {
        super.setup();
        this.action = useService("action");

        this.isProjectManager = false;
        onWillStart(async () => {
            if (this.props.list.isGroupedByStage) {
                this.isProjectManager = await user.hasGroup("project.group_project_manager");
            }
        });
    }

    // NB: deliberately no deleteGroup() override — inherit GroupConfigMenu's,
    // which shows a confirmation dialog before deleting a column. A previous
    // override called props.deleteGroup directly, deleting a relational group
    // (assignee, milestone, …) on a single unconfirmed click.

    canEditGroup() {
        return super.canEditGroup() && (!this.props.list.isGroupedByStage || this.isProjectManager);
    }

    canDeleteGroup() {
        return (
            super.canDeleteGroup() && (!this.props.list.isGroupedByStage || this.isProjectManager)
        );
    }
}
