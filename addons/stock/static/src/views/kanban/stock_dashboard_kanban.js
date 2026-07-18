/** @odoo-module native */
import { useSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";
import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { kanbanView } from "@web/views/kanban/kanban_view";

export class StockDashboardKanbanRenderer extends KanbanRenderer {
    setup() {
        super.setup();
        // Parsed graph JSON per record, keyed on the raw string so a record's
        // value is re-parsed only when it actually changes — not on every
        // render.
        this._graphCache = new WeakMap();
        // Renderer-local signal consumed by PickingTypeDashboardGraphField:
        // when every card's graph is server-tagged "sample" (no real data
        // anywhere on the dashboard), the graph fields render lively random
        // bars instead of flat zeros. The fabricated values stay local to the
        // field components — `record.data` is never written to.
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
