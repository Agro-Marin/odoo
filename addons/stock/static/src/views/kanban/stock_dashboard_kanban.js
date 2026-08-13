/** @odoo-module native */
import { useSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { DynamicGroupList, DynamicRecordList } from "@web/model/relational_model";
import { KanbanRenderer, kanbanView } from "@web/views/kanban";

export class StockDashboardKanbanRenderer extends KanbanRenderer {
    setup() {
        super.setup();
        this._graphCache = new WeakMap();
        useSubEnv({ stockDashboardAllSample: () => this.allGraphsAreSample() });
    }

    get dashboardRecords() {
        const { list } = this.props;
        if (list instanceof DynamicRecordList) {
            return list.records;
        } else if (list instanceof DynamicGroupList) {
            return list.groups.flatMap((group) => group.list.records);
        }
        return [];
    }

    allGraphsAreSample() {
        const records = this.dashboardRecords;
        return (
            records.length > 0 &&
            records.every((record) => {
                const data = this._parseGraph(record);
                return data?.[0]?.values?.every((value) => value.type === "sample");
            })
        );
    }

    _parseGraph(record) {
        const raw = record.data.kanban_dashboard_graph;
        let entry = this._graphCache.get(record);
        if (!entry || entry.raw !== raw) {
            let parsed;
            try {
                parsed = JSON.parse(raw);
            } catch {
                parsed = null;
            }
            entry = { raw, parsed };
            this._graphCache.set(record, entry);
        }
        return entry.parsed;
    }
}

export const stockDashboardKanbanView = {
    ...kanbanView,
    Renderer: StockDashboardKanbanRenderer,
};

registry.category("views").add("stock_dashboard_kanban", stockDashboardKanbanView);
