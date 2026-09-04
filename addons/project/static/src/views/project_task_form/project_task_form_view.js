/** @odoo-module native */
import { registry } from "@web/core/registry";
import { formViewWithHtmlExpander } from "@web/views/form_with_html_expander/form_view_with_html_expander";

import { ProjectTaskFormController } from "./project_task_form_controller.js";

export const projectTaskFormView = {
    ...formViewWithHtmlExpander,
    Controller: ProjectTaskFormController,
};

registry.category("views").add("project_task_form", projectTaskFormView);
