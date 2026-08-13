/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useOperationGuard } from "@stock/utils/use_operation_guard";
import { useService } from "@web/core/utils/hooks";

import { ReceptionReportLine } from "../reception_report_line/stock_reception_report_line.js";
import {
    assignMoves,
    buildLabelAction,
    collectAssignable,
    collectAssignedLabels,
    isLineAssignable,
} from "../reception_report_utils.js";

export class ReceptionReportTable extends Component {
    static template = "stock.ReceptionReportTable";
    static components = {
        ReceptionReportLine,
    };
    static props = {
        index: String,
        scheduledDate: { type: [String, Boolean], optional: true },
        lines: Array,
        source: Array,
        labelReport: Object,
        showUom: Boolean,
        precision: Number,
    };

    setup() {
        this.actionService = useService("action");
        this.ormService = useService("orm");
        this.opGuard = useOperationGuard();
        this.onClickAssignAll = this.opGuard.guard(this.onClickAssignAll.bind(this));
    }

    async onClickAssignAll() {
        const { moveIds, quantities, inIds } = collectAssignable(this.props.lines);
        await assignMoves(this.ormService, moveIds, quantities, inIds);
        this.env.bus.trigger("update-assign-state", {
            isAssigned: true,
            tableIndex: this.props.index,
        });
    }

    async onClickLink(resModel, resId, viewType) {
        return this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, viewType]],
            target: "current",
        });
    }

    async onClickPrintLabels() {
        const { docids, quantities } = collectAssignedLabels(this.props.lines);
        const action = buildLabelAction(this.props.labelReport, docids, quantities);
        if (action) {
            return this.actionService.doAction(action);
        }
    }

    get hasMovesIn() {
        return this.props.lines.some(
            (line) => line.move_ins && line.move_ins.length > 0,
        );
    }

    get hasAssignAllButton() {
        return this.props.lines.some((line) => line.is_qty_assignable);
    }

    get isAssignAllDisabled() {
        return (
            this.opGuard.busy ||
            this.props.lines.every((line) => !isLineAssignable(line))
        );
    }

    get isPrintLabelDisabled() {
        return this.props.lines.every((line) => !line.is_assigned);
    }
}
