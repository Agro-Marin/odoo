/** @odoo-module */
import { formView } from '@web/views/form/form_view';
import { ProjectSharingFormController } from './project_sharing_form_controller.js';
import { ProjectSharingFormRenderer } from './project_sharing_form_renderer.js';

formView.Controller = ProjectSharingFormController;
formView.Renderer = ProjectSharingFormRenderer;
