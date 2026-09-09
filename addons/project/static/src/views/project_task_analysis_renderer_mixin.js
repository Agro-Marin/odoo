/** @odoo-module native */
import { getShowSubtasks } from "@project/utils/project_utils";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";

export const ProjectTaskAnalysisRendererMixin = (T) =>
    class ProjectTaskAnalysisRendererMixin extends T {
        openView(domain, views, context, newWindow) {
            if (!getShowSubtasks()) {
                context.show_task_options = false;
            }
            const taskDomain = domain.map((leaf) =>
                Array.isArray(leaf) && leaf[0] === "task_id"
                    ? ["id", ...leaf.slice(1)]
                    : leaf,
            );
            const fieldsNotInBaseModel = [
                "nbr",
                "rating_last_value",
                "rating_avg",
                "delay_endings_days",
            ];
            const newDomain = Domain.removeDomainLeaves(
                taskDomain,
                fieldsNotInBaseModel,
            ).toList();

            this.actionService.doAction(
                {
                    context,
                    domain: newDomain,
                    name: _t("Tasks"),
                    res_model: "project.task",
                    target: "current",
                    type: "ir.actions.act_window",
                    views,
                },
                {
                    newWindow,
                    viewType: "list",
                },
            );
        }
    };
