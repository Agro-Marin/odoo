/** @odoo-module native */
import { AccountReport } from "@account/components/account_report/account_report";
import { AccountReportLine } from "@account/components/account_report/line/line";
import { PartnerLedgerFollowupLineCell } from "@account/components/partner_ledger_followup/line_cell/line_cell";

export class PartnerLedgerFollowupLine extends AccountReportLine {
    static template = "account.PartnerLedgerFollowupLine";
    static components = {
        ...AccountReportLine.components,
        PartnerLedgerFollowupLineCell,
    };
}
AccountReport.registerCustomComponent(PartnerLedgerFollowupLine);
