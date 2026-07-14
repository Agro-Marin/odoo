/** @odoo-module native */
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/l10n/translation";
import { getShowSubtasks } from "@project/utils/project_utils";

export const ProjectTaskAnalysisRendererMixin = (T) => class ProjectTaskAnalysisRendererMixin extends T {
    /**
     * Drill down on project.task instead of the analysis report model.
     * NB: no search_view_id is forwarded on purpose — the current one belongs
     * to the report model, not to project.task.
     */
    openView(domain, views, context, newWindow) {
        if (!getShowSubtasks()) {
            context.show_task_options = false;
        }
        // Map report leaves onto task leaves without mutating `domain`: it is
        // the model's cached group domain, not a copy.
        const taskDomain = domain.map((leaf) =>
            Array.isArray(leaf) && leaf[0] === "task_id" ? ["id", ...leaf.slice(1)] : leaf
        );
        const fieldsNotInBaseModel = ["nbr", "rating_last_value", "rating_avg", "delay_endings_days"];
        const newDomain = Domain.removeDomainLeaves(taskDomain, fieldsNotInBaseModel).toList();

        this.actionService.doAction({
            context,
            domain: newDomain,
            name: _t("Tasks"),
            res_model: "project.task",
            target: "current",
            type: "ir.actions.act_window",
            views,
        }, {
            newWindow,
            viewType: "list",
        });
    }
}
