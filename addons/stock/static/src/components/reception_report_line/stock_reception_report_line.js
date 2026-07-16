/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/fields/formatters";

import { assignMoves, buildLabelAction } from "../reception_report_utils.js";

export class ReceptionReportLine extends Component {
    static template = "stock.ReceptionReportLine";
    static props = {
        data: Object,
        labelReport: Object,
        parentIndex: String,
        showUom: Boolean,
        precision: Number,
    };

    setup() {
        this.ormService = useService("orm");
        this.actionService = useService("action");
        this.formatFloat = (val) =>
            formatFloat(val, { digits: [false, this.props.precision] });
    }

    //---- Handlers ----

    async onClickForecast() {
        const action = await this.ormService.call(
            "stock.move",
            "action_product_forecast_report",
            [[this.data.move_out_id]],
        );

        return this.actionService.doAction(action);
    }

    async onClickPrint() {
        if (!this.data.move_out_id) {
            return;
        }
        const action = buildLabelAction(
            this.props.labelReport,
            [this.data.move_out_id],
            [Math.ceil(this.data.quantity) || 1],
        );
        return this.actionService.doAction(action);
    }

    async onClickAssign() {
        await assignMoves(
            this.ormService,
            [this.data.move_out_id],
            [this.data.quantity],
            [this.data.move_ins],
        );
        this.env.bus.trigger("update-assign-state", {
            isAssigned: true,
            tableIndex: this.props.parentIndex,
            lineIndex: this.data.index,
        });
    }

    async onClickUnassign() {
        const done = await this.ormService.call(
            "report.stock.report_reception",
            "action_unassign",
            [false, this.data.move_out_id, this.data.quantity, this.data.move_ins],
        );
        if (done) {
            this.env.bus.trigger("update-assign-state", {
                isAssigned: false,
                tableIndex: this.props.parentIndex,
                lineIndex: this.data.index,
            });
        }
    }

    //---- Getters ----

    get data() {
        return this.props.data;
    }
}
