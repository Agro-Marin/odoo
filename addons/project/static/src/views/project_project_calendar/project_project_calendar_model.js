/** @odoo-module native */

import { CalendarModel } from '@web/views/calendar/calendar_model';
import { ProjectModelMixin } from '../project_model_mixin.js';

export class ProjectCalendarModel extends ProjectModelMixin(CalendarModel) {}
