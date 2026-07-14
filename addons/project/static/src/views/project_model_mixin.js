/** @odoo-module native */
import { Domain } from "@web/core/domain";

export const ProjectModelMixin = (T) => class ProjectModelMixin extends T {
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
        if (
            this.env.searchModel.resModel === "project.project" &&
            this.env.searchModel.context?.render_project_templates
        ) {
            return Domain.and([
                Domain.removeDomainLeaves(domain, ['is_template']).toList(),
                [['is_template', '=', true]],
            ]).toList({});
        }
        return domain;
    }
}
