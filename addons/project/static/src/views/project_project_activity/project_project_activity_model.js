/** @odoo-module native */
import { ActivityModel } from "@mail/views/web/activity/activity_model";
import { ProjectModelMixin } from "../project_model_mixin.js";

export class ProjectActivityModel extends ProjectModelMixin(ActivityModel) {}
