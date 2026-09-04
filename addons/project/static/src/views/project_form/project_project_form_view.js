/** @odoo-module native */
import { registry } from "@web/core/registry";
import { formViewWithHtmlExpander } from "@web/views/form_with_html_expander/form_view_with_html_expander";

import { ProjectProjectFormController } from "./project_project_form_controller.js";

export const projectProjectFormView = {
    ...formViewWithHtmlExpander,
    Controller: ProjectProjectFormController,
};

registry.category("views").add("project_project_form", projectProjectFormView);
