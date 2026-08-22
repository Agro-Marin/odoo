/** @odoo-module native */
import { DomainSelector } from "@web/components/domain_selector";
import { patch } from "@web/core/utils/patch";

patch(DomainSelector.prototype, {
    /**
     * @override
     */
    getShowArchivedCheckBox(_, props) {
        if (props.resModel === "documents.document") {
            return false;
        }
        return super.getShowArchivedCheckBox(...arguments);
    },
});
