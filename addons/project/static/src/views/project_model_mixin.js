/** @odoo-module native */
import { Domain } from "@web/core/domain";

export const ProjectModelMixin = (T) =>
    class ProjectModelMixin extends T {
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
                    Domain.removeDomainLeaves(domain, ["is_template"]).toList(),
                    [["is_template", "=", true]],
                ]).toList({});
            }
            return domain;
        }
    };
