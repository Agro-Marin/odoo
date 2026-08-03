/** @odoo-module native */

import { CalendarModel } from "@web/views/calendar";

import { ProjectModelMixin } from "../project_model_mixin.js";

export class ProjectCalendarModel extends ProjectModelMixin(CalendarModel) {}
