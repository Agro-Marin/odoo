/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { useOperationGuard } from "@stock/utils/use_operation_guard";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { standardActionServiceProps } from "@web/webclient/actions";

import { ReceptionReportTable } from "../reception_report_table/stock_reception_report_table.js";
import {
    assignMoves,
    buildLabelAction,
    collectAssignable,
    collectAssignedLabels,
    isLineAssignable,
} from "../reception_report_utils.js";

export class ReceptionReportMain extends Component {
    static template = "stock.ReceptionReportMain";
    static components = {
        ControlPanel,
        ReceptionReportTable,
    };
    static props = { ...standardActionServiceProps };

    setup() {
        this.controlPanelDisplay = {};
        this.ormService = useService("orm");
        this.actionService = useService("action");
        this.reportName = "stock.report_reception";
        this.labelReportName = "stock.report_reception_report_label";
        this.state = useState({
            sourcesToLines: {},
        });
        useBus(this.env.bus, "update-assign-state", (ev) =>
            this._changeAssignedState(ev.detail),
        );
        this.opGuard = useOperationGuard();
        this.onClickAssignAll = this.opGuard.guard(this.onClickAssignAll.bind(this));

        onWillStart(async () => {
            let defaultDocIds;
            const { rfield, rids } = this.props.action.context.params || {};
            if (rfield && rids) {
                try {
                    const parsedIds = JSON.parse(rids);
                    defaultDocIds = [
                        rfield,
                        parsedIds instanceof Array ? parsedIds : [parsedIds],
                    ];
                } catch (error) {
                    // Restored from a URL someone edited; fall through to the
                    console.warn("[stock] unreadable reception report ids:", error);
                }
            }
            if (!defaultDocIds) {
                const defaultEntry = Object.entries(this.context).find(([k]) =>
                    k.startsWith("default_"),
                );
                if (defaultEntry) {
                    const [field, value] = defaultEntry;
                    defaultDocIds = [field, Array.isArray(value) ? value : [value]];
                } else {
                    defaultDocIds = [false, [0]];
                }
            }
            this.contextDefaultDoc = { field: defaultDocIds[0], ids: defaultDocIds[1] };

            if (this.contextDefaultDoc.field) {
                this.props.updateActionState({
                    rfield: this.contextDefaultDoc.field,
                    rids: JSON.stringify(this.contextDefaultDoc.ids),
                });
            }
            this.data = await this.getReportData();
            this.state.sourcesToLines = this.data.sources_to_lines;

            const matchingReports = await this.ormService.searchRead(
                "ir.actions.report",
                [["report_name", "in", [this.reportName, this.labelReportName]]],
            );
            this.receptionReportAction = matchingReports.find(
                (report) => report.report_name === this.reportName,
            );
            this.receptionReportLabelAction = matchingReports.find(
                (report) => report.report_name === this.labelReportName,
            );
        });
    }

    async getReportData() {
        const context = {
            ...this.context,
            [this.contextDefaultDoc.field]: this.contextDefaultDoc.ids,
        };
        const args = [this.contextDefaultDoc.ids, { context, report_type: "html" }];
        return this.ormService.call(
            "report.stock.report_reception",
            "get_report_data",
            args,
            { context },
        );
    }

    async onClickAssignAll() {
        const lines = Object.values(this.state.sourcesToLines).flat();
        const { moveIds, quantities, inIds } = collectAssignable(lines);
        if (!moveIds.length) {
            return;
        }
        await assignMoves(this.ormService, moveIds, quantities, inIds);
        this._changeAssignedState({ isAssigned: true });
    }

    async onClickTitle(docId) {
        return this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: this.data.doc_model,
            res_id: docId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onClickPrint() {
        return this.actionService.doAction({
            ...this.receptionReportAction,
            context: { [this.contextDefaultDoc.field]: this.contextDefaultDoc.ids },
        });
    }

    onClickPrintLabels() {
        const lines = Object.values(this.state.sourcesToLines).flat();
        const { docids, quantities } = collectAssignedLabels(lines);
        const action = buildLabelAction(
            this.receptionReportLabelAction,
            docids,
            quantities,
        );
        if (action) {
            return this.actionService.doAction(action);
        }
    }

    _changeAssignedState(options) {
        const { isAssigned, tableIndex, lineIndex } = options;
        const isBulk = lineIndex === undefined;

        for (const [tabIndex, lines] of Object.entries(this.state.sourcesToLines)) {
            if (tableIndex && tableIndex !== tabIndex) {
                continue;
            }
            lines.forEach((line) => {
                if (!isBulk && lineIndex !== line.index) {
                    return;
                }
                if (isBulk && isAssigned && !isLineAssignable(line)) {
                    return;
                }
                line.is_assigned = isAssigned;
            });
        }
    }

    get context() {
        return this.props.action.context;
    }

    get hasContent() {
        return (
            this.data.sources_to_lines &&
            Object.keys(this.data.sources_to_lines).length > 0
        );
    }

    get isAssignAllDisabled() {
        return (
            this.opGuard.busy ||
            Object.values(this.state.sourcesToLines).every((lines) =>
                lines.every((line) => !isLineAssignable(line)),
            )
        );
    }

    get isPrintLabelDisabled() {
        return Object.values(this.state.sourcesToLines).every((lines) =>
            lines.every((line) => !line.is_assigned),
        );
    }
}

registry.category("actions").add("reception_report", ReceptionReportMain);
