/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { GroupConfigMenu } from "@web/views/view_components";

export class ProjectGroupConfigMenu extends GroupConfigMenu {
    static stageFieldName = "";

    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");

        this.isProjectManager = false;
        onWillStart(async () => {
            if (this.isStageGroup) {
                this.isProjectManager = await user.hasGroup(
                    "project.group_project_manager",
                );
            }
        });
    }

    get isStageGroup() {
        return this.group.groupByField.name === this.constructor.stageFieldName;
    }

    async deleteGroup() {
        if (!this.isStageGroup) {
            return super.deleteGroup();
        }
        const { context, groupByField, value } = this.group;
        const action = await this.orm.call(
            groupByField.relation,
            "action_open_delete_wizard",
            [[value]],
            {
                context,
            },
        );
        this.action.doAction(action, {
            onClose: (infos) => {
                if (infos?.success) {
                    this.props.list.load();
                }
            },
        });
    }

    canEditGroup() {
        return super.canEditGroup() && (!this.isStageGroup || this.isProjectManager);
    }

    canDeleteGroup() {
        return super.canDeleteGroup() && (!this.isStageGroup || this.isProjectManager);
    }
}
