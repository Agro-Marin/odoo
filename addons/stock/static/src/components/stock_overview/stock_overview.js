/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";

import { DynamicRecordList } from "@web/model/relational_model/dynamic_record_list";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";

export class StockKanbanRenderer extends KanbanRenderer {
    // If all Inventory Overview graphs are empty, we use random sample data
    getGroupsOrRecords() {
        const { list } = this.props;
        let records = [];
        if (list instanceof DynamicRecordList) {
            records.push(...list.records);
        } else if (list instanceof DynamicGroupList) {
            list.groups.forEach(g => {
                records.push(...g.list.records);
            });
        }
        // Python tags empty graph data with type "sample" (and a null
        // picking_type_id). When every card is empty we replace the flat zeros
        // with lively random bars. Detection is parse-based (robust to JSON
        // whitespace), and each record is randomised only once (tracked in a
        // WeakSet) so the bars stay stable across re-renders instead of
        // re-randomising on every render.
        this._sampledRecords ??= new WeakSet();
        const parsed = records.map((r) => {
            try {
                return JSON.parse(r.data.kanban_dashboard_graph);
            } catch {
                return null;
            }
        });
        const allEmpty =
            parsed.length &&
            parsed.every((p) => p && p[0]?.values?.every((v) => v.type === "sample"));
        if (allEmpty) {
            records.forEach((r, i) => {
                if (this._sampledRecords.has(r)) {
                    return;
                }
                const data = parsed[i];
                data[0].values.forEach((d) => {
                    d.value = Math.floor(Math.random() * 9 + 1);
                });
                r.data.kanban_dashboard_graph = JSON.stringify(data);
                this._sampledRecords.add(r);
            });
        }
        return super.getGroupsOrRecords();
    }
}

export const StockKanbanView = {
    ...kanbanView,
    Renderer: StockKanbanRenderer,
};

registry.category("views").add("stock_dashboard_kanban", StockKanbanView);
