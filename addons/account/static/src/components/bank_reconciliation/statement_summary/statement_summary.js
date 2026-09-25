/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useSearchModel } from "@web/search/search_model";

export const bankRecStatementSummaryProps = {
    label: { type: String },
    amount: { type: String, optional: true },
    action: { type: Function },
    journalId: { type: Number, optional: true },
    isValid: { type: Boolean, optional: true },
    journalIsInvalid: { type: Boolean, optional: true },
};

export class BankRecStatementSummary extends Component {
    static template = "account.BankRecStatementSummary";

    static props = bankRecStatementSummaryProps;
    static defaultProps = {
        isValid: true,
    };

    setup() {
        super.setup();
        this.searchModel = useSearchModel();
    }

    actionApplyInvalidStatement() {
        const facets = this.searchModel.facets;
        const searchItems = this.searchModel.searchItems;
        const invalidStatementFilter = Object.values(searchItems).find(
            (i) => i.name === "invalid_statement",
        );
        const invalidStatementFacet = facets.filter(
            (i) => i.groupId === invalidStatementFilter.groupId,
        );
        if (
            invalidStatementFacet.length === 0 ||
            !invalidStatementFacet[0].values.includes(
                invalidStatementFilter.description,
            )
        ) {
            this.searchModel.toggleSearchItem(invalidStatementFilter.id);
        }
    }
}
