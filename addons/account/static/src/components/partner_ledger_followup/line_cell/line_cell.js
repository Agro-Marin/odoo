/** @odoo-module native */
import { useAccountReportContext } from "@report_formula/components/account_report/account_report_context";
import { AccountReportLineCell } from "@report_formula/components/account_report/line_cell/line_cell";

export class PartnerLedgerFollowupLineCell extends AccountReportLineCell {
    static template = "account.PartnerLedgerFollowupLineCell";

    setup() {
        super.setup();
        this.reportContext = useAccountReportContext();
    }

    async toggleNoFollowup(ev) {
        const res = await this.orm.call(
            "account.partner.ledger.report.handler",
            "action_toggle_no_followup",
            [this.props.line.id, this.controller.lines.map((line) => line.id)],
        );
        this.controller.updateLines(
            res.updated_line_ids,
            "no_followup",
            res.updated_value,
        );
    }
}
