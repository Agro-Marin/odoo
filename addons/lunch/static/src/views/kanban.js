/** @odoo-module native */
import { registry } from '@web/core/registry';

import {
    kanbanView,
    KanbanRecord,
    KanbanRenderer,
    KanbanController,
} from "@web/views/kanban";

import { LunchDashboard } from '../components/lunch_dashboard.js';
import { LunchRendererMixin } from '../mixins/lunch_renderer_mixin.js';

import { LunchSearchModel } from './search_model.js';
import { LunchSearchPanel } from './search_panel.js';

export class LunchKanbanRecord extends KanbanRecord {
    onGlobalClick(ev) {
        this.env.bus.trigger('lunch_open_order', {productId: this.props.record.resId});
    }
}

export class LunchKanbanRenderer extends LunchRendererMixin(KanbanRenderer) {
    static template = "lunch.KanbanRenderer";
    static components = {
        ...LunchKanbanRenderer.components,
        LunchDashboard,
        KanbanRecord: LunchKanbanRecord,
    };

    getGroupsOrRecords() {
        const { locationId } = this.env.searchModel.lunchState;
        if (!locationId) {
            return [];
        } else {
            return super.getGroupsOrRecords(...arguments);
        }
    }
}

class LunchKanbanController extends KanbanController {
    get modelOptions() {
        return {
            ...super.modelOptions,
            lazy: false,
        };
    }
}

registry.category('views').add('lunch_kanban', {
    ...kanbanView,
    Controller: LunchKanbanController,
    Renderer: LunchKanbanRenderer,
    SearchModel: LunchSearchModel,
    SearchPanel: LunchSearchPanel,
});
