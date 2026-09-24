/** @odoo-module native */
import { registry } from "@web/core/registry";

import {
    kanbanView,
    KanbanRecord,
    KanbanRenderer,
    KanbanController,
} from "@web/views/kanban";

import { LunchDashboard } from "../components/lunch_dashboard.js";
import { LunchRendererMixin } from "../mixins/lunch_renderer_mixin.js";

import { LunchSearchModel } from "./search_model.js";
import { LunchSearchPanel } from "./search_panel.js";
import { useService, useEventBus } from "@web/core/utils/hooks";
import { useSearchModel } from "@web/search/search_model";

export class LunchKanbanRecord extends KanbanRecord {
    setup() {
        super.setup();
        this.bus = useEventBus();
    }

    onGlobalClick() {
        this.bus.trigger("lunch_open_order", {
            productId: this.props.record.resId,
        });
    }
}

export class LunchKanbanRenderer extends LunchRendererMixin(KanbanRenderer) {
    static template = "lunch.KanbanRenderer";
    static components = {
        ...LunchKanbanRenderer.components,
        LunchDashboard,
        KanbanRecord: LunchKanbanRecord,
    };

    setup() {
        super.setup();
        this.searchModel = useSearchModel();
        this.ui = useService("ui");
    }

    getGroupsOrRecords() {
        const { locationId } = this.searchModel.lunchState;
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

registry.category("views").add("lunch_kanban", {
    ...kanbanView,
    Controller: LunchKanbanController,
    Renderer: LunchKanbanRenderer,
    SearchModel: LunchSearchModel,
    SearchPanel: LunchSearchPanel,
});
