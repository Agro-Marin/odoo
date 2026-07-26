/** @odoo-module native */
import { activityView } from "@mail/views/web/activity/activity_view";
import { registry } from "@web/core/registry";

import { ProjectActivityModel } from "./project_project_activity_model.js";

export const projectProjectActivityView = {
    ...activityView,
    Model: ProjectActivityModel,
};

registry.category("views").add("project_project_activity", projectProjectActivityView);
