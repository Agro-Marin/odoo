/** @odoo-module native */
import { StockValuationReportLine } from "./line.js";

export class StockValuationReportToggleLine extends StockValuationReportLine {
    static template = "stock_account.StockValuationReport.InventoryValuationToggleLine";
}

StockValuationReportToggleLine.components.StockValuationReportToggleLine =
    StockValuationReportToggleLine;
