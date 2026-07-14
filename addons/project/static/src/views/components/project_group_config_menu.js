/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { user } from "@web/services/user";
import { useService } from "@web/core/utils/hooks";
import { GroupConfigMenu } from "@web/views/view_components/group_config_menu";

/**
 * Column-header config menu for views groupable by a stage-like many2one
 * (`step_id` on tasks, `phase_id` on projects) whose records must not be
 * edited or deleted by non-managers, and whose deletion goes through a
 * server-side `unlink_wizard` (archive vs delete choice for non-empty
 * stages) instead of a raw unlink.
 *
 * This lives at the component level, not in the model's DynamicGroupList:
 * the model layer has no action service to open the wizard with, and the
 * same component is shared by the kanban and the grouped list, so both get
 * identical gating and wizard behavior.
 */
export class ProjectGroupConfigMenu extends GroupConfigMenu {
    /** Stage-like m2o field whose groups are manager-gated and wizard-deleted. */
    static stageFieldName = "";

    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");

        this.isProjectManager = false;
        onWillStart(async () => {
            if (this.isStageGroup) {
                this.isProjectManager = await user.hasGroup("project.group_project_manager");
            }
        });
    }

    get isStageGroup() {
        return this.group.groupByField.name === this.constructor.stageFieldName;
    }

    /**
     * Stage columns: open the unlink wizard, which is itself the confirmation
     * (so the generic "delete this column?" dialog is skipped) and decides
     * between archiving and deleting. Other relational columns keep the
     * generic confirm + raw unlink from the base class.
     */
    async deleteGroup() {
        if (!this.isStageGroup) {
            return super.deleteGroup();
        }
        const { context, groupByField, value } = this.group;
        const action = await this.orm.call(groupByField.relation, "unlink_wizard", [[value]], {
            context,
        });
        this.action.doAction(action, {
            onClose: (infos) => {
                // `infos` is only provided when the wizard confirmed
                // (archive/delete); a plain dismiss closes with undefined.
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
