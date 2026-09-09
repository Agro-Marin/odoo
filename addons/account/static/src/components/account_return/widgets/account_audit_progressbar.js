/** @odoo-module native */
import { ProgressBarField, progressBarField } from "@web/fields/display/progress_bar";
import { registry } from "@web/core/registry";
export class AccountAuditProgressbar extends ProgressBarField {
    static template = "account.AccountAuditProgressBar";

    get progressBarColorClass() {
        if (this.maxValue == 0) {
            return "";
        }
        return this.currentValue > this.maxValue
            ? this.props.overflowClass
            : "bg-success";
    }

    get maxValue() {
        return this.props.record.data[this.maxValueFieldName];
    }

    get hasMaxValue() {
        return this.maxValueFieldName in this.props.record.data;
    }
}

export const AccountAuditProgressBarField = {
    ...progressBarField,
    component: AccountAuditProgressbar,
};

registry
    .category("fields")
    .add("account_audit_progressbar", AccountAuditProgressBarField);
