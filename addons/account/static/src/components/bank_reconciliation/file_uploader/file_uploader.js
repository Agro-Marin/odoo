/** @odoo-module native */
import { DocumentFileUploader } from "@account/components/document_file_uploader/document_file_uploader";

export class BankRecFileUploader extends DocumentFileUploader {
    /** @returns {Object} */
    getExtraContext() {
        const extraContext = super.getExtraContext();
        return {
            ...extraContext,
            statement_line_id: this.props.record.statementLineId,
        };
    }

    getResModel() {
        return "account.bank.statement.line";
    }
}
