/** @odoo-module native */
import { useSubEnv } from "@odoo/owl";
import { readJsonValue } from "@stock/utils/json_field";
import { registry } from "@web/core/registry";
import { DynamicGroupList, DynamicRecordList } from "@web/model/relational_model";
import { KanbanRenderer, kanbanView } from "@web/views/kanban";

export class StockDashboardKanbanRenderer extends KanbanRenderer {
    setup() {
        super.setup();
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
        return readJsonValue(
            record,
            record.data.kanban_dashboard_graph,
            null,
            "kanban_dashboard_graph",
        );
    }
}

export const stockDashboardKanbanView = {
    ...kanbanView,
    Renderer: StockDashboardKanbanRenderer,
};

registry.category("views").add("stock_dashboard_kanban", stockDashboardKanbanView);
