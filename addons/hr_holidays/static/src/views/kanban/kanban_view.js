/** @odoo-module native */
import { kanbanView } from '@web/views/kanban/kanban_view';
import { registry } from '@web/core/registry';
import { TimeOffKanbanRenderer } from './kanban_renderer.js';
import { TimeOffKanbanController } from './kanban_controller.js';

const TimeOffKanbanView = {
    ...kanbanView,
    Renderer: TimeOffKanbanRenderer,
    Controller: TimeOffKanbanController
}

registry.category('views').add('time_off_kanban_dashboard', TimeOffKanbanView);
