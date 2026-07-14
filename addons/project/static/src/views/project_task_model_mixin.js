/** @odoo-module native */
import { Domain } from "@web/core/domain";
import { getShowSubtasks } from "../utils/project_utils.js";

export const ProjectTaskModelMixin = (T) => class ProjectTaskModelMixin extends T {
    /**
     * Process the search domain only when the caller actually provides one
     * (search-driven loads). Parameterless reloads (view buttons, archive
     * refresh, calendar navigation) reuse the domain the base class already
     * stores — which is the OUTPUT of a previous _processSearchDomain call:
     * re-processing it would append a duplicate injected leaf per reload, and
     * a truthy params.domain needlessly resets pagination to offset 0.
     */
    async load(params = {}) {
        if (params.domain) {
            params.domain = this._processSearchDomain(params.domain);
        }
        return super.load(params);
    }

    _processSearchDomain(domain) {
        const { my_tasks, subtask_action } = this.env.searchModel.globalContext;
        const showSubtasks = my_tasks || subtask_action || getShowSubtasks();
        if (['project.task', 'report.project.task.user'].includes(this.env.searchModel.resModel) && !showSubtasks) {
            domain = Domain.and([
                domain,
                [['display_in_project', '=', true]],
            ]).toList({});
        }
        if (this.env.searchModel.context?.render_task_templates) {
            domain = Domain.removeDomainLeaves(domain, [
                'has_template_ancestor',
                'has_project_template',
                'project_id.is_template',
            ]);
            const templateTaskDomain = Domain.or([
                [['has_template_ancestor', '=', true]],
                'default_project_id' in this.env.searchModel.globalContext
                    ? Domain.TRUE
                    : [['project_id.is_template', '=', true]],
            ]);
            domain = Domain.and([domain, templateTaskDomain]).toList({});
        }
        return domain;
    }
}
