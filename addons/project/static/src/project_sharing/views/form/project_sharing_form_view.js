/** @odoo-module native */
import { formView } from "@web/views/form";

import { ProjectSharingFormController } from "./project_sharing_form_controller.js";
import { ProjectSharingFormRenderer } from "./project_sharing_form_renderer.js";

formView.Controller = ProjectSharingFormController;
formView.Renderer = ProjectSharingFormRenderer;
